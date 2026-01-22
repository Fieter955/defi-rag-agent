@echo off
echo Menjalankan Chandra OCR via KoboldCPP...
koboldcpp.exe ^
  --model Chandra-OCR-Q6_K.gguf ^
  --mmproj mmproj-F16.gguf ^
  --gpulayers 99 ^
  --context 8192 ^
  --port 5001
pause