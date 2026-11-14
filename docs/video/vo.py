import subprocess, json
segs=[(0,7,"A real photo. A fake caption. This crowd is Copacabana beach in Rio, not a Trump rally in New Jersey."),
(7,5,"Provenance checks the claim behind any image or X post."),
(12,6,"Drop in an image, an X post, or a claim."),
(18,7,"Here, the Copacabana photo and its viral caption. Then watch the tools work."),
(25,9,"Treg's Google Lens finds where the image came from. Treg searches news, the web, and X. And You.com reads credible sources and decides if they back the claim."),
(34,8,"You get one clear answer, up to three reasons, and the sources."),
(42,6,"GTA 6's release date: True, from Rockstar. The Reuters post on X: True."),
(48,6,"The Wildwood rally photo: Misleading."),
(54,9,"Built with You.com, Treg, and XDC, with a two-cent paywall ready for apps and agents."),
(63,7,"Check it before you share it.")]
inputs=[];filt=[]
for i,(st,d,t) in enumerate(segs):
    f=f"vo{i}.mp3"
    subprocess.run(["python3","-m","edge_tts","--voice","en-US-AndrewNeural","--rate=+5%","--text",t,"--write-media",f],check=True)
    dur=float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f]))
    room=d-0.4
    tempo=max(1.0,dur/room)
    print(i,round(dur,2),room,round(tempo,2))
    inputs+=["-i",f]
    filt.append(f"[{i}:a]atempo={tempo:.3f},adelay={int((st+0.2)*1000)}|{int((st+0.2)*1000)}[v{i}]")
filt.append("".join(f"[v{i}]" for i in range(len(segs)))+f"amix=inputs={len(segs)}:normalize=0,apad=whole_dur=70[vo]")
subprocess.run(["ffmpeg","-loglevel","error","-y",*inputs,"-filter_complex",";".join(filt),"-map","[vo]","-ar","48000","-ac","2","-t","70","vo.wav"],check=True)
