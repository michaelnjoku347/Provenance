set -e
D=deck/docs/pitch
F=/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf
FB=/usr/share/fonts/truetype/macos/Inter-Bold.ttf
i=0
seg(){ # img dur zoomEnd cx cy line1 line2
  i=$((i+1)); n=$(printf %02d $i); fr=$(( $2*30 ))
  printf '%s' "$6" > t${n}a.txt; printf '%s' "$7" > t${n}b.txt
  ffmpeg -loglevel error -y -loop 1 -i "$1" -vf "scale=3840:2160:force_original_aspect_ratio=increase,crop=3840:2160,zoompan=z='1+($3-1)*on/$fr':x='($4)*(iw-iw/zoom)':y='($5)*(ih-ih/zoom)':d=$fr:s=1920x1080:fps=30,drawbox=y=ih-190:w=iw:h=190:color=black@0.78:t=fill,drawtext=fontfile=$FB:textfile=t${n}a.txt:fontsize=50:fontcolor=white:x=(w-tw)/2:y=h-160,drawtext=fontfile=$F:textfile=t${n}b.txt:fontsize=34:fontcolor=0xD8F45A:x=(w-tw)/2:y=h-88,fade=in:st=0:d=0.3,fade=out:st=$(python3 -c "print($2-0.3)"):d=0.3,format=yuv420p" -t $2 -c:v libx264 -preset veryfast -crf 20 s${n}.mp4
}
seg $D/img/copacabana-crowd.jpg 7 1.12 0.5 0.5 "A real photo. A fake caption." "Viral post: \"Trump rally in Wildwood, NJ.\" It's Copacabana beach in Rio."
seg $D/png/02-problem.png 5 1.05 0.5 0.4 "Miscaptioned media spreads faster than fact checks." "Provenance checks a claim before you share it."
seg shots/home.png 6 1.06 0.2 0.3 "Provenance: drop in a claim, an X post link, or an image." "Running locally with the repo's sample claims."
seg shots/filled.png 7 1.5 0.0 0.2 "The Copacabana photo, plus its viral caption." "One click: Check claim."
seg live169.png 9 1.12 0.0 0.2 "Watch the tools work live." "Treg Lens · Treg News, Web, X · You.com Search, Contents, Research"
seg $D/png/03-what-it-does.png 8 1.06 0.5 0.4 "One clear answer." "Verdict badge · up to 3 reasons · 2-3 sources · Why this confidence"
seg $D/png/05-live-examples.png 6 1.25 1.0 0.15 "GTA 6 release date: TRUE.   Reuters on X: TRUE." "Confirmed by Rockstar's own sources · matches Reuters reporting"
seg $D/png/05-live-examples.png 6 1.3 1.0 0.95 "\"Trump rally in Wildwood, NJ\": MISLEADING." "It's Copacabana beach in Rio, miscaptioned."
seg $D/png/06-sponsor-tools.png 9 1.05 0.5 0.4 "Built with You.com, Treg, XDC and OpenCrawl." "XDC x402: \$0.02 per check, paywall ready · Gemini for image understanding"
seg $D/png/08-close.png 7 1.04 0.5 0.5 "Check it before you share it." "github.com/michaelnjoku347/Provenance"
ls s*.mp4 | sed "s/^/file '/;s/$/'/" > list.txt
ffmpeg -loglevel error -y -f concat -safe 0 -i list.txt -c copy -movflags +faststart out.mp4
