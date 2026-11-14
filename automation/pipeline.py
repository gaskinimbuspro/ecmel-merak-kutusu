"""Render an approved episode with Magic Hour, then assemble it locally."""
import argparse
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent
API = "https://api.magichour.ai/v1"
PROFILES = {
    "kling": ("kling-4.0", "720p", 80),
    "karma": ("minimax-h3", "720p", 48),
    "ekonomik": ("minimax-h3", "480p", 24),
}
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
REF = re.compile(r"@([a-z][a-z0-9_]*)")


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def local_settings():
    return read_json(ROOT / "credentials.local.json", {})


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def safe_id(value):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        raise ValueError("Bölüm kodu küçük Latin harfleri, rakam ve tire içerebilir.")
    return value


def build_plan(manifest, profile):
    title = manifest["title"].strip()
    if not title or len(title) > 100:
        raise ValueError("YouTube başlığı 1–100 karakter olmalı.")
    description = manifest["description"].strip()
    sources = manifest["sources"]
    if not sources or any(urllib.parse.urlsplit(url).scheme != "https" for url in sources):
        raise ValueError("Bölüm için doğrulanmış HTTPS kaynak bağlantılarını ekle.")
    description += "\n\nKaynaklar\n" + "\n".join(sources)
    if len(description.encode()) > 5000:
        raise ValueError("YouTube açıklaması en fazla 5000 bayt olabilir.")
    references = {key: ROOT / Path(value).expanduser() for key, value in manifest["references"].items()}
    if profile not in PROFILES:
        raise ValueError("Bilinmeyen model profili.")
    plan = []
    for index, scene in enumerate(manifest["scenes"], 1):
        seconds = scene["seconds"]
        if type(seconds) is not int or not 3 <= seconds <= 30:
            raise ValueError("Her sahne 3–30 tam saniye olmalı.")
        item = {"index": index, "seconds": seconds}
        if "file" in scene:
            if "prompt" in scene:
                raise ValueError(f"Sahne {index} için bir dosya veya bir prompt gir.")
            item.update(file=str(ROOT / Path(scene["file"]).expanduser()), estimated=0)
        else:
            prompt = scene["prompt"].strip()
            if not prompt:
                raise ValueError(f"Sahne {index} için prompt boş.")
            selected = sorted(set(REF.findall(prompt)))
            if set(selected) - set(references):
                raise ValueError(f"Sahne {index} bilinmeyen @referans kullanıyor.")
            use_kling = profile == "kling" or (profile == "karma" and scene.get("kind") != "doga")
            model, resolution, credits = PROFILES["kling" if use_kling else profile]
            item.update(
                prompt=prompt,
                images={key: str(references[key]) for key in selected},
                model=model,
                resolution=resolution,
                audio=scene.get("kind") != "doga" or use_kling,
                estimated=seconds * credits,
            )
            if any(Path(path).suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} for path in item["images"].values()):
                raise ValueError("Görsel referanslar PNG, JPG veya WebP olmalı.")
        plan.append(item)
    duration = sum(scene["seconds"] for scene in plan)
    if not 30 <= duration <= 90:
        raise ValueError("Bölüm toplamı 30–90 saniye olmalı.")
    return {
        "title": title, "description": description, "duration": duration, "scenes": plan,
        "estimated": sum(scene["estimated"] for scene in plan),
    }


def api(path, token, body=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(API + path, data=data, headers=headers)
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def remote_file(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("Magic Hour güvenli bir dosya bağlantısı döndürmedi.")
    return url


def upload_references(scene, token, state, save):
    result = []
    cache = state.setdefault("images", {})
    for name, filename in scene["images"].items():
        local = Path(filename)
        content = local.read_bytes()
        fingerprint = hashlib.sha256(content).hexdigest()
        if fingerprint not in cache:
            items = [{"type": "image", "extension": local.suffix.lower()[1:]}]
            slot = api("/files/upload-urls", token, {"items": items})["items"][0]
            headers = {"Content-Type": mimetypes.guess_type(local.name)[0] or "application/octet-stream"}
            request = urllib.request.Request(remote_file(slot["upload_url"]), data=content, headers=headers, method="PUT")
            with urllib.request.urlopen(request, timeout=90):
                pass
            cache[fingerprint] = slot["file_path"]
            save()
        result.append({"name": name, "file_path": cache[fingerprint]})
    return result


def await_clip(project_id, token, destination, deadline):
    while time.monotonic() < deadline:
        status = api("/video-projects/" + urllib.parse.quote(project_id, safe=""), token)
        if status["status"] == "complete":
            temporary = destination.with_suffix(".part")
            with urllib.request.urlopen(remote_file(status["downloads"][0]["url"]), timeout=120) as response:
                with temporary.open("wb") as stream:
                    shutil.copyfileobj(response, stream)
            temporary.replace(destination)
            return
        if status["status"] in {"error", "failed", "canceled"}:
            raise ValueError(f"Magic Hour işi {project_id} başarısız. Hesap geçmişinden ayrıntıya bak.")
        time.sleep(12)
    raise ValueError(f"Magic Hour işi {project_id} sürüyor. Aynı bölüm koduyla yeniden çalıştır.")


def render_clips(plan, run, state, token, ceiling, wait_seconds):
    clips = []
    for scene in plan["scenes"]:
        if "file" in scene:
            clips.append(Path(scene["file"]))
            continue
        index = str(scene["index"])
        dest = run / f"sahne-{index}.mp4"
        clips.append(dest)
        if dest.exists():
            continue
        jobs = state.setdefault("jobs", {})
        job = jobs.get(index)
        if job is None:
            if sum(x.get("charged", x["estimate"]) for x in jobs.values()) + scene["estimated"] > ceiling:
                raise ValueError("Sonraki sahnenin tahmini kredi tavanını aşıyor.")
            state_path = run / "state.json"
            def save():
                write_json(state_path, state)

            refs = upload_references(scene, token, state, save)
            payload = {
                "name": f"{run.name} sahne {index}", "end_seconds": scene["seconds"],
                "aspect_ratio": "9:16", "resolution": scene["resolution"], "model": scene["model"],
                "audio": scene["audio"], "style": {"prompt": scene["prompt"]},
            }
            if refs:
                payload["references"] = refs
            job = jobs[index] = {"estimate": scene["estimated"]}
            save()
            try:
                response = api("/text-to-video", token, payload)
            except urllib.error.HTTPError as error:
                if error.code in {400, 401, 402, 403, 404, 422, 429}:
                    del jobs[index]
                    save()
                raise
            job.update(id=response["id"], charged=response.get("credits_charged") or scene["estimated"])
            save()
            if sum(x.get("charged", x["estimate"]) for x in jobs.values()) > ceiling:
                raise ValueError("Magic Hour bildirilen tahmini aştı. Diğer sahneler gönderilmedi.")
        if "id" not in job:
            raise ValueError(f"Sahne {index} için gönderim belirsiz. Magic Hour geçmişini kontrol et ve iş numarasını onar.")
        await_clip(job["id"], token, dest, time.monotonic() + wait_seconds)
    return clips


def ffmpeg_binary():
    ffmpeg = os.environ.get("FFMPEG_BIN") or local_settings().get("ffmpeg_bin") or shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    raise ValueError("FFmpeg bulunamadı. Yükle veya FFMPEG_BIN ayarla.")


def inspect_clip(ffmpeg, clip):
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(clip)], capture_output=True, text=True)
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    if not duration or "Video:" not in result.stderr:
        raise ValueError(f"Klipte okunabilir görüntü bulunmalı: {clip}")
    hours, minutes, seconds = map(float, duration.groups())
    return hours * 3600 + minutes * 60 + seconds, "Audio:" in result.stderr


def assemble(plan, clips, run, custom_ambience):
    ffmpeg = ffmpeg_binary()
    metadata = [inspect_clip(ffmpeg, clip) for clip in clips]
    for scene, clip, (duration, has_audio) in zip(plan["scenes"], clips, metadata):
        if scene.get("audio", True) and not has_audio:
            raise ValueError(f"Konuşma beklenen klipte ses kanalı yok: {clip}")
        if abs(duration - scene["seconds"]) > 0.65:
            raise ValueError(f"Klip süresi plandan farklı: {clip}")
    total = plan["duration"]
    ambience = run / "bahce.wav"
    if custom_ambience:
        ambience = custom_ambience
    elif not ambience.exists():
        subprocess.run([sys.executable, str(ROOT / "garden_audio.py"), str(ambience), str(total)], check=True)

    inputs = [arg for clip in clips for arg in ("-i", str(clip))]
    filters = []
    for index, scene in enumerate(plan["scenes"]):
        seconds = scene["seconds"]
        filters.extend([
            f"[{index}:v]fps=24,scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,"
            f"setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=0.65,trim=duration={seconds},setpts=PTS-STARTPTS[v{index}]",
        ])
        if metadata[index][1]:
            filters.append(f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,highpass=f=70,"
                           f"apad=whole_dur={seconds},atrim=duration={seconds},asetpts=PTS-STARTPTS[a{index}]")
        else:
            filters.append(f"anullsrc=r=48000:cl=stereo:d={seconds}[a{index}]")
    scene_outputs = "".join(f"[v{i}][a{i}]" for i in range(len(clips)))
    filters.extend([
        f"{scene_outputs}concat=n={len(clips)}:v=1:a=1[v][dialogue]",
        f"[{len(clips)}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=duration={total},"
        f"volume=0.8,afade=t=out:st={total-1}:d=1[ambient]",
        "[dialogue]volume=0.9,asplit=2[dry][key]",
        "[ambient][key]sidechaincompress=threshold=0.027:ratio=5:attack=30:release=450[bed]",
        "[dry][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=0:latency=1[a]",
    ])
    destination = run / "video.mp4"
    temporary = run / "video.render.mp4"
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", *inputs, "-stream_loop", "-1", "-i", str(ambience),
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]", "-t", str(total),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(temporary),
    ], check=True)
    temporary.replace(destination)
    return destination


@contextmanager
def locked_run(run):
    run.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (run / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("Bu bölüm koduyla bir işlem zaten çalışıyor.") from error
        yield


def run_episode(args):
    override = json.loads(base64.b64decode(args.form)) if args.form else {}
    name = safe_id(override.get("episode") or args.episode)
    profile = override.get("profile") or args.profile
    mode = override.get("mode") or args.mode
    budget = override.get("budget")
    ceiling = int(args.budget if budget is None else budget)
    manifest_path = ROOT / "episodes" / f"{name}.json"
    manifest = json.loads(override["manifest"]) if (override.get("manifest") or "").strip() else read_json(manifest_path)
    if not manifest:
        manifest = (read_json(ROOT / "runs" / name / "taslak.json") or {}).get("manifest")
    if not manifest:
        raise ValueError(f"Senaryo bulunamadı: {manifest_path}")
    plan = build_plan(manifest, profile)
    if mode == "plan":
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return
    if mode != "uret":
        raise ValueError("Bilinmeyen çalışma modu.")
    if ceiling < 0 or plan["estimated"] > ceiling:
        raise ValueError(f"Tahmin {plan['estimated']} kredi, tavan {ceiling}. Üretim başlamadı.")
    ffmpeg = ffmpeg_binary()
    for scene in plan["scenes"]:
        for file in ([scene["file"]] if "file" in scene else scene["images"].values()):
            if not Path(file).is_file():
                raise ValueError(f"Dosya bulunamadı: {file}")
        if "file" in scene:
            duration, has_audio = inspect_clip(ffmpeg, scene["file"])
            if abs(duration - scene["seconds"]) > 0.65 or not has_audio:
                raise ValueError(f"Sahne {scene['index']} dosyasının sesini ve süresini kontrol et.")
    token = os.environ.get("MAGIC_HOUR_API_KEY") or local_settings().get("magic_hour_api_key")
    if plan["estimated"] and not token:
        raise ValueError("Magic Hour API anahtarını yerel ayarlara ekle.")

    run = ROOT / "runs" / name
    with locked_run(run):
        state_path = run / "state.json"
        saved = read_json(state_path, {"plan": plan})
        if (run / "youtube.json").exists():
            raise ValueError("Bu bölüm bir YouTube yüklemesine bağlı. Düzenlenen kopyayı yeni bir bölüm koduyla oluştur.")
        if saved["plan"] != plan:
            raise ValueError("Bu bölüm kodu farklı bir üretim planına bağlı.")
        write_json(state_path, saved)
        clips = render_clips(plan, run, saved, token, ceiling, args.wait)
        ambience_path = args.ambience or local_settings().get("ambience_file")
        custom_ambience = Path(ambience_path).expanduser() if ambience_path else None
        destination = assemble(plan, clips, run, custom_ambience)
    print(json.dumps({"file": str(destination), "seconds": plan["duration"],
                      "estimated": plan["estimated"], "title": plan["title"]}, ensure_ascii=False))


def draft(args):
    form = json.loads(base64.b64decode(args.form))
    name = safe_id(form.get("episode"))
    question = form["question"].strip()
    setting = (form.get("setting") or "Bahçe veya kamp. Soruya uygun olanı seç.").strip()
    if not question or len(question) > 600 or len(setting) > 1000:
        raise ValueError("Kısa bir soru ve sahne bağlamı gir.")
    portraits = ROOT / "assets" / "magichour-karakterler"
    references = {
        "kiz": str(portraits / "ecmel-video.png"),
        "baba": str(portraits / "gokhan-siyah-mont.png"),
        "anne": str(portraits / "beyza-kamp.png"),
    }
    manifest_path = ROOT / "episodes" / f"{name}.json"
    draft_path = ROOT / "runs" / name
    with locked_run(draft_path):
        if manifest_path.exists():
            raise ValueError("Bu bölüm kodu zaten kullanılıyor.")
        if (draft_path / "state.json").exists():
            raise ValueError("Bu kod üretime verilmiş. Yeni soru için başka bir bölüm kodu seç.")
        cached = read_json(draft_path / "taslak.json")
        if cached and cached["question"] == question and cached["setting"] == setting:
            print(json.dumps(cached["manifest"], ensure_ascii=False, indent=2))
            return
        instructions = (ROOT / "bolum-standardi.txt").read_text() + "\n"
        codex = shutil.which("codex")
        if not codex:
            raise ValueError("Soru formu için Codex CLI kurulu olmalı.")
        with TemporaryDirectory(prefix="ecmel-taslak-") as temporary:
            folder = Path(temporary)
            output = folder / "response.json"
            subprocess.run([
                codex, "--search", "--ask-for-approval", "never", "exec", "--sandbox", "read-only",
                "--ignore-user-config", "--ephemeral", "--skip-git-repo-check", "--cd", str(folder),
                "--output-schema", str(ROOT / "senaryo.schema.json"), "--output-last-message", str(output), "-",
            ], input=instructions + json.dumps({"soru": question, "mekan": setting}, ensure_ascii=False),
                text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=480, check=True)
            manifest = read_json(output)
        if not manifest or len(set(manifest["sources"])) < 2:
            raise ValueError("Taslak için iki ayrı bilimsel kaynak bulunamadı.")
        manifest["references"] = references
        build_plan(manifest, "kling")
        write_json(draft_path / "taslak.json", {"question": question, "setting": setting, "manifest": manifest})
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def publish(args):
    form = json.loads(base64.b64decode(args.form))
    name = safe_id(form.get("episode"))
    title, description = form["title"].strip(), form["description"].strip()
    if not title or len(title) > 100 or len(description.encode()) > 5000:
        raise ValueError("YouTube başlığını ve açıklamasını kontrol et.")
    if form.get("visibility") not in {"private", "unlisted", "public"}:
        raise ValueError("YouTube görünürlüğünü seç.")
    run = ROOT / "runs" / name
    with locked_run(run):
        if not (run / "video.mp4").is_file():
            raise ValueError("Bölümün final MP4 dosyası bulunamadı.")
        journal = run / "youtube.json"
        if journal.exists():
            raise ValueError("Bu bölüm için bir YouTube yükleme kaydı var. Yeniden göndermeden önce kaydı ve Studio'yu kontrol et.")
        data = {"title": title, "description": description, "visibility": form["visibility"],
                "episode": name, "file": str(run / "video.mp4")}
        write_json(journal, data)
        print(json.dumps(data, ensure_ascii=False))


def record(args):
    data = json.loads(base64.b64decode(args.form))
    run = ROOT / "runs" / safe_id(data.get("episode"))
    video_id = data.get("video_id")
    if not isinstance(video_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("YouTube video kimliği dönmedi. YouTube Studio'yu kontrol et.")
    with locked_run(run):
        journal = run / "youtube.json"
        saved = read_json(journal)
        if not saved:
            raise ValueError("YouTube yükleme kaydı bulunamadı.")
        result = {**saved, "video_id": video_id, "url": "https://www.youtube.com/watch?v=" + video_id}
        write_json(journal, result)
        print(result["url"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="subcommand", required=True)
    episode = subcommands.add_parser("episode")
    episode.add_argument("--episode", default="kelebekler")
    episode.add_argument("--mode", choices=["plan", "uret"], default="plan")
    episode.add_argument("--profile", choices=PROFILES, default="kling")
    episode.add_argument("--budget", type=int, default=4800)
    episode.add_argument("--wait", type=int, default=1200, help="Sahne başına bekleme süresi, saniye")
    episode.add_argument("--ambience", help="Kullanım izni olan müzik ve doğa sesi dosyası")
    episode.add_argument("--form")
    for name in ("draft", "publish", "record"):
        subcommands.add_parser(name).add_argument("--form", required=True)
    args = parser.parse_args()
    try:
        {"episode": run_episode, "draft": draft, "publish": publish, "record": record}[args.subcommand](args)
    except urllib.error.HTTPError as error:
        print(f"Magic Hour HTTP {error.code}. Hesap erişimini, planı veya proje geçmişini kontrol et.", file=sys.stderr)
        sys.exit(1)
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
