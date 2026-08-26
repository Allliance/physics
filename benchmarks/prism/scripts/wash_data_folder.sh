: "${TOGETHER_API_KEY:?Set TOGETHER_API_KEY in the environment}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY in the environment}"

INPUT_DIR="Seephys/ours_jsons"
OUTPUT_DIR="Seephys/ours_jsons/rewritten"
MODEL="gpt-4.1"
NUM_STAGES="1 2 3"

mkdir -p "$OUTPUT_DIR"

FILES=("$INPUT_DIR"/*.json)

echo "Found ${#FILES[@]} files:"
for f in "${FILES[@]}"; do
  echo "  - $f"
done

for input_file in "${FILES[@]}"; do
  filename=$(basename "$input_file")
  output_file="$OUTPUT_DIR/$filename"              # Seephys/ours_jsons/rewritten/merge_xyz.json

  echo "Processing $input_file -> $output_file"

  python -m data.wash_data \
    --raw "$input_file" \
    --out "$output_file" \
    --model "$MODEL" \
    --start -1 \
    --end -1 \
    --max-attempts 3 \
    --num-stages $NUM_STAGES

  python -m data.wash_data_postprocess \
    --input_file "$output_file" \
    --output_file "${output_file%.json}_postprocessed.json"
done
