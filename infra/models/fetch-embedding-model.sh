#!/usr/bin/env bash
# Telecharge le modele d'embeddings et verifie ses empreintes (PR 37b).
# Usage : infra/models/fetch-embedding-model.sh <dossier>
#
# Memes fichiers et memes SHA-256 que l'etape `model` de backend/Dockerfile (un test le
# verifie : tests/unit/test_embedding_model_pins.py). Sert a l'evaluation avec le vrai modele
# dans la CI ; l'image, elle, telecharge par ADD --checksum.
set -euo pipefail

dest="${1:?usage : $0 <dossier>}"
mkdir -p "$dest"

fetch() {
  local url="$1" sha="$2" file="$3"
  curl --fail --silent --show-error --location --retry 3 --output "$dest/$file.part" "$url"
  echo "$sha  $dest/$file.part" | sha256sum --check --quiet
  mv "$dest/$file.part" "$dest/$file"
}

fetch "https://huggingface.co/Xenova/multilingual-e5-small/resolve/97cb8f96eaed1a1f0dac821239943e854fce9c36/onnx/model_quantized.onnx" \
  "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193" model.onnx
fetch "https://huggingface.co/intfloat/multilingual-e5-small/resolve/main/tokenizer.json" \
  "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39" tokenizer.json

echo "Modele d'embeddings verifie dans $dest"
