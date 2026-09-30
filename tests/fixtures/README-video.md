`adwatch-video-playback.webm` is an eight-second synthetic moving test pattern
(VP8, 160 × 90, 10 fps, no audio), used to verify decoded Chromium playback
without an external media service. It contains no third-party content.

Regenerate with:

```sh
ffmpeg -f lavfi -i testsrc=size=160x90:rate=10 -t 8 -c:v libvpx -b:v 40k -an -y tests/fixtures/adwatch-video-playback.webm
```
