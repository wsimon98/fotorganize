#!/usr/bin/env bash
# Export a LoRA dataset for a person (Linux).
# Usage: export_person_lora.sh "George Clooney" [trigger_word]
cd "$(dirname "$0")/../backend"
[ -x venv/bin/python ] || { echo "run scripts/setup_linux.sh first"; exit 1; }
[ -z "$1" ] && { echo 'Usage: export_person_lora.sh "PersonName" [trigger_word]'; exit 1; }
if [ -z "$2" ]; then
  venv/bin/python -m photoindex export-lora --person "$1" --zip
else
  venv/bin/python -m photoindex export-lora --person "$1" --trigger "$2" --zip
fi
echo "Output is under data/exports/"
