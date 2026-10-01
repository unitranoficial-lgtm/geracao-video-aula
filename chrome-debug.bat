@echo off
REM Abre o Chrome com porta de debug ativa (necessario para o flow_automation.py)
REM Execute este .bat UMA vez antes de rodar o script quando o Chrome ja estiver aberto.
REM Depois de configurar o atalho com --remote-debugging-port=9222, nao precisa mais deste arquivo.

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --profile-directory="Profile 3" ^
  --remote-debugging-port=9222

echo Chrome iniciado com porta de debug 9222.
echo Aguarde o Chrome abrir e faca login se necessario.
pause
