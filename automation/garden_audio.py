import math
import random
import struct
import wave
from pathlib import Path
from sys import argv

rate = 44100
duration = int(argv[2])
beat = 60 / 84
track = [0.0] * (rate * duration)
birds = [0.0] * len(track)

def note(start,pitch,length,gain,bass=False):
    i0 = round(start * rate)
    increment = math.tau * (440 * 2 ** ((pitch - 69) / 12)) / rate
    for i in range(min(round(length*rate),len(track)-i0)):
        t = i / rate
        envelope = (1-math.exp(-t/.018))*math.exp(-t/(.75 if bass else .46))*min(1,(length-t)/.22)
        x = increment * i
        voice = math.sin(x) + .14*math.sin(2*x)*math.exp(-t/.34)
        if not bass:
            voice += .09*math.sin(3*x)*math.exp(-t/.14)
        track[i0+i] += gain*envelope*voice

bars = [
    (48,55,[(0,72),(1.5,76),(2.5,79)]),
    (45,52,[(.5,76),(2,72)]),
    (41,48,[(0,69),(1.5,72),(3,76)]),
    (43,50,[(.5,74),(1.5,71),(3,74)]),
    (48,55,[(0,76),(1,79),(2.5,81)]),
    (45,52,[(.5,76),(2.5,72)]),
    (41,48,[(0,69),(2,72)]),
    (43,50,[(0,74),(1.5,71),(3,74)]),
]
for bar in range(math.ceil(duration / (4 * beat))):
    root_pitch,fifth,melody=bars[bar%len(bars)]
    note(4*bar*beat,root_pitch,2.2,.034,True)
    note((4*bar+2)*beat,fifth,1.5,.018,True)
    for offset,pitch in melody:
        note((4*bar+offset)*beat,pitch,1.5,.047)

rng=random.Random(618)
for start, n, strength in [(0.14,3,1),(4.6,3,.47),(8.8,4,1.1),(11.3,2,.72),(24.9,4,.94),
                            (30.8,3,.57),(38.6,2,.35),(46.9,3,.62),(54.3,2,.42),
                            (61.8,4,.7),(66.6,4,1),(71.0,3,.61),(74,2,.65),
                            (77,3,.50),(81,4,.65),(87,3,.61)]:
    if start >= duration:
        continue
    for j in range(n):
        begin = start+j*rng.uniform(.16,.26)
        length=rng.uniform(.10,.18)
        gain=strength*rng.uniform(.032,.053)
        base=rng.uniform(1850,2670)
        sweep=rng.uniform(750,1480)
        if j%3==2:
            sweep=-sweep*.57
        index=round(begin*rate)
        for i in range(min(round(length*rate),len(birds)-index)):
            t=i/rate
            phase=math.tau*(base*t+sweep*(t*t/(2*length)))+.23*math.sin(math.tau*47*t)
            envelope=math.sin(math.pi*t/length)**1.7
            birds[index+i]+=gain*envelope*(math.sin(phase)+.15*math.sin(2*phase))

output=bytearray()
low=0
wind=0
for i,(melody,chirp) in enumerate(zip(track,birds)):
    t=i/rate
    ramp=min(1,t/.45,(duration-t)/1.03)
    pause=max(0,min(1,(t-8.7)/.8,(13.2-t)/.55))
    swell=max(0,min(1,(t-63)/1.3,(67.1-t)/.7))
    score=melody*(.65+.37*pause+.17*swell)
    raw=rng.uniform(-1,1)
    low=.988*low+.012*raw
    wind=.85*wind+.15*raw
    air=(.021*low+.004*wind)*(.73+.27*math.sin(t*.69))
    output.extend(struct.pack('<hh',round(32767*ramp*(score+air+.71*chirp)),round(32767*ramp*(score*.95+air+1.06*chirp))))

with wave.open(str(Path(argv[1])),'wb') as wav:
    wav.setparams((2,2,rate,0,'NONE','not compressed'))
    wav.writeframes(output)
