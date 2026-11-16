#!/usr/bin/env bash
set -euo pipefail

# Timing: each screenshot remains visible for 0.8s.
DISPLAY_DUR=0.8
TARGET_WIDTH=713
TARGET_HEIGHT=310
OUTPUT_FPS=1.25
PALETTE_COLORS=256
OUTPUT_GIF="themes_cycle.gif"

mapfile -t frames < <(find . -maxdepth 1 -type f \( -name 'Screenshot_1_white.png' -o -name 'Screenshot_theme_*.png' \) -printf '%f\n' | sort)

if [[ ${#frames[@]} -lt 2 ]]; then
  echo "Need at least 2 theme screenshots"
  exit 1
fi

inputs=()
filter=""
concat_inputs=""
for i in "${!frames[@]}"; do
  inputs+=( -loop 1 -t "$DISPLAY_DUR" -i "${frames[$i]}" )
  filter+="[$i:v]scale=$TARGET_WIDTH:$TARGET_HEIGHT:force_original_aspect_ratio=decrease:flags=lanczos,pad=$TARGET_WIDTH:$TARGET_HEIGHT:(ow-iw)/2:(oh-ih)/2:color=black@0,format=rgba,setsar=1[v$i];"
  concat_inputs+="[v$i]"
done

filter+="${concat_inputs}concat=n=${#frames[@]}:v=1:a=0[video];"

ffmpeg -y "${inputs[@]}" \
  -filter_complex "$filter[video]fps=$OUTPUT_FPS,split[s0][s1];[s0]palettegen=max_colors=$PALETTE_COLORS:stats_mode=single[p];[s1][p]paletteuse=new=1:dither=sierra2_4a" \
  -loop 0 "$OUTPUT_GIF"

echo "Created $OUTPUT_GIF from ${#frames[@]} screenshots without transitions."
