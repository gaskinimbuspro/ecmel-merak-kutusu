# Ecmel’in Merak Kutusu

Mac üzerinde n8n, Magic Hour API ve FFmpeg ile 30–90 saniyelik dikey bölümler. Magic Hour sahneleri ve Türkçe replikleri üretir. FFmpeg onaylanan klipleri birleştirir, konuşma duyulurken alçalan bir müzik ve bahçe sesi katmanı ekler. YouTube formu, biten MP4 dosyasını verdiğin başlık, açıklama ve görünürlükle yükler.

Kanalın seçilen profil görseli Mac’te `assets/kanal/youtube-profil.png`. Karakter referanslarını `assets/magichour-karakterler/` altında tut. Bu dosyalar yerel üretim girdileridir.

## İlk kurulum

1. Mac’teki n8n ve Python kullanılabilir. Yerel ayar dosyasındaki geçici FFmpeg yolu kaybolursa kalıcı FFmpeg için `brew install ffmpeg` kullan veya FFmpeg yolunu ayar dosyasında belirt.
2. `credentials.example.json` dosyasını aynı klasörde `credentials.local.json` adıyla kopyala. [Magic Hour Developer Hub](https://magichour.ai/developer) üzerinden aldığın anahtarı `magic_hour_api_key` değerine kendi Mac’inde yaz. Dosyayı kaynak kontrolüne ekleme. İsteğe bağlı `ambience_file` alanına kullanım izni olan müzik ve bahçe kaydını içeren yerel bir ses dosyası gir. Alan boşken akış hafif özgün melodi, sentetik kuş ötüşü ve rüzgâr kullanır.
3. Aşağıdaki komutlarla n8n’i bu projeye özel bir klasörde ve yalnızca bu Mac’ten erişilebilen adreste başlat. Mevcut n8n kurulumuna eklemek istersen JSON’ları Workflow ekranından içe aktar. Dışarıya açık bir sunucuda çalıştırırsan formlara kimlik doğrulama ekle.
4. Kanalı aşağıdaki “YouTube’u n8n’e bağla” adımlarıyla bağla.

```sh
cd automation
sh n8n-local.sh init
sh n8n-local.sh start
```

İçe aktarmayı ilk kurulumda bir kez çalıştır. `http://localhost:5679` adresinde kurulumunu tamamla. Her akışın **Form Trigger** düğümünden formu önce test edebilir, ardından akışı etkinleştirip Production URL’yi kullanabilirsin. Mac’in ve n8n’in açık olması gerekir. `n8n-local.sh` akışların `pipeline.py` dosyasını bulacağı çalışma klasörünü ayarlar.

## YouTube’u n8n’e bağla

1. Seriye ayrı bir kanal açacaksan YouTube’daki kanal listesinden o kanalı oluştur. Kanalın adını ve benzersiz kullanıcı adını seç. [YouTube kanal oluşturma rehberi](https://support.google.com/youtube/answer/1646861)
2. Yerel n8n panelinde **Ecmel · 02 YouTube’a yükle → YouTube Shorts yükle** düğümünü aç. **YouTube OAuth2 API** bağlantısını oluştur ve n8n’in gösterdiği **OAuth Redirect URL** adresini kopyala.
3. Google Cloud projesinde **YouTube Data API v3** hizmetini etkinleştir. **Google Auth Platform → Clients** bölümünde **Web application** türünde OAuth istemcisi oluştur ve kopyaladığın adresi **Authorized redirect URIs** alanına ekle. Uygulama Testing durumundaysa kendi Google hesabını test kullanıcısı olarak ekle. Google, Testing durumundaki harici uygulamalarda bu izinlerin yedi gün sürebildiğini belirtiyor. [n8n Google OAuth kurulumu](https://docs.n8n.io/integrations/builtin/credentials/google/oauth-single-service/) · [Google Auth Platform kitle ayarları](https://support.google.com/cloud/answer/15549945)
4. Client ID ve Client Secret değerlerini n8n ekranına gir. **Connect my account** ile Google izin ekranını aç ve seri kanalını seç. YouTube düğümüne bu bağlantıyı kaydet. Akıştan ilk yüklemeyi **private** görünürlükle dene ve doğru kanalda göründüğünü kontrol et.
5. Sonraki yüklemelerde n8n formundan bölüm kodu ve görünürlük seçilir. n8n dosyayı YouTube Data API’ye gönderir. Mac ve n8n çalışırken tarayıcıda bir Studio yükleme penceresi açmak gerekmez. [YouTube Data API yükleme kılavuzu](https://developers.google.com/youtube/data/guides/uploading_a_video)

## Bölüm standardı

[Senaryo yazım standardı](bolum-standardi.txt) yeni bölüm taslaklarına otomatik uygulanır. 50–65 saniye başlangıç aralığıdır. Kızın bir şeyi fark eder, baba ona dönüp tepki verir. Açıklama başladığında kamera canlıya geçer ve hareketi babanın ilgili kelimeleriyle aynı anda gösterir. Kapanışta kız gördüğünü kendi kelimeleriyle anlatır. Daha uzun süre, izleyicinin bir deneyi veya doğal hareketi takip etmesine zaman kazandırıyorsa kullanılır.

## Bir bölüm nasıl ilerler?

- **Yeni soru** formuna bölüm kodunu, çocuğun sorusunu ve isteğe bağlı mekânı yaz. Yerel Codex CLI, açık oturumunu kullanarak kaynaklı bir Türkçe senaryo taslağı hazırlar. Bu adım Magic Hour kredisi tüketmez ve Codex kullanım hakkından düşebilir. Çıktıyı Executions ekranında veya `runs/<kod>/taslak.json` dosyasında görürsün. Bilimsel cümleleri, iki kaynağı ve replikleri kontrol et. Düzeltmek istediğinde taslağın `manifest` içeriğini Bölüm üret formunun Senaryo JSON alanına yapıştırabilirsin.
- **Bölüm üret** formunda aynı bölüm kodunu gir. İlk bölüm için kod `kelebekler`. Aynı açılışla 60 saniyelik kısa kurgu `kelebekler-kisa`, daha sıcak oyunculuk ve kelebek yakın planlarıyla hazırlanan sürüm `kelebekler-samimi` kodundadır. Önce `plan` modu süre ve tahmini krediyi gösterir. `uret` modunda akış yeni klipleri üretir, proje numaralarını kaydeder, indirir ve `runs/<kod>/video.mp4` oluşturur. Daha önce oluşturulmuş yerel kliplerden kredi düşmez. Dosyalar hâlâ Downloads içindeyse kelebek pilotu ek girdi istemez.
- **YouTube’a yükle** formunda biten videoyu izledikten sonra bölüm kodunu, başlığı, kaynaklı açıklamayı ve görünürlüğü seç. Bu formu göndermek YouTube yükleme talebidir. Başlıkta soruyu doğrudan kullanabilirsin. Kitle ayarı Çocuklara özel. Video bağlantısı `runs/<kod>/youtube.json` içinde kaydedilir.

Sıradaki [Kuşların Kulakları Nerede?](episodes/kuslarin-kulaklari.json) bölümü ormanda kamp sabahında geçer. Bölüm üret formunda `kuslarin-kulaklari` ve `plan` girerek süreyi ve kredi hesabını görebilirsin.

## Kredi hesabı

| 25 sn hazır + 60 sn yeni içerik | Tahmin |
| --- | ---: |
| İki konuşmalı sahne, Kling 4.0 720p | 4.800 |
| Kısa kurgu, 25 + 15 + 20 saniye, Kling 4.0 720p | 2.800 |
| 30 sn konuşma Kling 4.0 720p, 30 sn yalnızca doğa MiniMax H3 720p | 3.840 |
| İki sahne MiniMax H3 480p | 1.440 |

Karma profil bir sahneyi ancak senaryoda `kind: "doga"` ile işaretlenmiş ve konuşmasız olarak planlanmışsa MiniMax H3 kullanarak üretir. Kelebek pilotundaki iki devam sahnesi de konuşmalı. Ekonomik profilde yüzleri ve Türkçe replikleri kısa bir sahnede kıyasla. 480p klipler finalde 720×1280’e ölçeklenir.

Mevcut Kling ücretini 80 kredi/sn, H3 ücretini 720p’de 48 ve 480p’de 24 kredi/sn olarak hesaplıyoruz. Video referansı kullanmayan profil bu ücretlere göre plan yapar. Magic Hour API gerçek tahsilatı istek kabul edildikten sonra bildirir. Oranlar değişirse ilk istek tahmini aşabilir. Akış bu farkı gördüğünde sonraki istekleri durdurur. Aynı bölüm koduyla başarılı sahneler tekrar gönderilmez. Bir isteğin alınıp alınmadığı belirsizse Magic Hour History’den proje numarasını doğrula ve `state.json` dosyasında ilgili işe ekle. YouTube yanıtı kesildiyse ikinci yüklemeden önce Studio’da kontrol et.

45–60 saniyelik bölümlerde yalnızca gereken saniyeleri üretmek maliyeti doğrudan azaltır. Platformun büyümesini izlemek için YouTube Studio’da ilk saniyelerde kaç kişinin kaldığını ve izleyici tutma grafiğini incele. Kızının gerçek sorusu ve kamp ya da bahçede başlayan farklı bir gözlem, her bölümün kendi hikâyesini kurar. [YouTube Shorts analitiği](https://support.google.com/youtube/answer/12942217) · [Magic Hour Kling 4.0](https://magichour.ai/models/kling-4-0) · [MiniMax H3](https://magichour.ai/models/minimax-h3)

Planı terminalden de görebilirsin.

```sh
python3 pipeline.py episode --episode kelebekler --mode plan
```
