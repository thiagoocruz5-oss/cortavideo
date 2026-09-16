# CortaVídeo

MVP local para transformar um MP4 em cortes verticais de 30 a 60 segundos. Interface em português, transcrição real com faster-whisper, sugestões por densidade de fala e finais de frases, ajuste de intervalo, prévia central, legendas opcionais e exportação com FFmpeg.

## Como rodar

1. Instale **Python 3.11 ou 3.12** de https://www.python.org/downloads/ (no Windows, marque “Add Python to PATH”).
2. Instale **FFmpeg com ffprobe e filtro subtitles/libass**: https://ffmpeg.org/download.html. Coloque a pasta `bin` no PATH. No macOS com Homebrew: `brew install ffmpeg`. No Ubuntu: `sudo apt install ffmpeg`.
3. Abra um terminal nesta pasta e execute:

```sh
python -m venv .venv
```

No Windows PowerShell, sem precisar ativar o ambiente:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe preparar_modelo.py
.\.venv\Scripts\python.exe app.py
```

No macOS/Linux:

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python preparar_modelo.py
.venv/bin/python app.py
```

4. Abra **http://127.0.0.1:8001**. Envie um MP4, aguarde a transcrição, escolha uma sugestão, ajuste início/fim em segundos e clique em **Exportar corte**. Depois clique em **Baixar MP4**.

## O que esperar

- Upload máximo: 1 GB. Duração de entrada: 30 segundos a 2 horas.
- A preparação baixa o modelo Whisper `base` e precisa de internet. A transcrição usa exclusivamente a cópia local, sem chave de API e sem enviar mídia a um serviço de transcrição. Em CPU, vídeos longos podem levar vários minutos.
- Idioma detectado automaticamente. Para maior precisão, configure `WHISPER_MODEL=small` antes de iniciar (mais memória e tempo de processamento).
- Exportação: 720 × 1280, H.264/AAC, proporção 9:16. A barra abaixo da prévia ajusta a posição horizontal: 0% esquerda, 50% centro e 100% direita. A posição é preservada por sugestão enquanto a página está aberta e aplicada ao MP4. Vídeos sem sobra lateral não se deslocam; vídeos muito estreitos perdem conteúdo acima/abaixo.
- Legendas são gravadas no MP4, em grupos de até seis palavras. A prévia HTML aproxima a aparência; o FFmpeg renderiza as legendas finais. Revise a transcrição, pois ela pode conter erros.
- Sem áudio/fala: o app permite um corte manual e desabilita legendas. Sugestões não são uma avaliação de potencial de viralização.
- Uma tarefa de processamento por vez. A interface informa a etapa, sem estimativa artificial de porcentagem.
- Arquivos ficam em `data/`. O histórico das tarefas existe apenas em memória: ao reiniciar, reenvie o vídeo. Para liberar espaço, pare o servidor e apague os arquivos dentro de `data/` que não precisar mais.
- Uso individual local: o servidor escuta apenas em `127.0.0.1`. Não exponha esta versão diretamente à internet.

## Verificação e problemas comuns

### Falha de conexão com o Hub ao transcrever

O modelo precisa ser baixado uma vez. No PowerShell, com acesso à internet, execute nesta pasta:

```powershell
.\.venv\Scripts\python.exe preparar_modelo.py
```

No macOS/Linux, use `.venv/bin/python preparar_modelo.py`. O modelo é validado e salvo em `models/base/`. Reinicie o servidor após atualizar o código. Com essa cópia pronta, a transcrição não consulta o Hugging Face. Para outro modelo, use o mesmo `WHISPER_MODEL` na preparação e no servidor. Não apague `models/` se quiser continuar usando offline.

### FFmpeg instalado, mas não reconhecido no Windows

O aplicativo consulta também o PATH atual salvo no Windows e a instalação pelo WinGet, mesmo se o terminal tiver sido aberto antes da instalação. A mesma detecção é usada no upload e no processamento. Depois de atualizar o código, encerre o servidor com Ctrl+C e inicie-o novamente.

Para instalações em uma pasta personalizada, configure os caminhos completos antes de iniciar:

```powershell
$env:FFMPEG_PATH = 'C:\ferramentas\ffmpeg\bin\ffmpeg.exe'
$env:FFPROBE_PATH = 'C:\ferramentas\ffmpeg\bin\ffprobe.exe'
.\.venv\Scripts\python.exe app.py
```

Também é possível colocar ambos os executáveis na pasta `bin/` do projeto.

```sh
ffmpeg -version
ffprobe -version
ffmpeg -filters
python -m unittest discover -s tests -v
```

Na lista de filtros, confira `subtitles`. Se faltar, instale uma distribuição do FFmpeg com libass. Se o navegador não reproduzir o MP4 original, ele pode usar um codec não suportado pelo navegador; tente a exportação, que converte para H.264. Erros de download do Whisper normalmente pedem verificar internet, proxy ou espaço em disco. Para encerrar o servidor, pressione Ctrl+C.

## Organização e próximas melhorias

- `app.py`: servidor, upload em blocos, fila e download com suporte a intervalos.
- `processing.py`: transcrição, sugestões, legendas e FFmpeg sem comandos de shell.
- `static/`: interface responsiva sem dependências de frontend.
- `processing.framing_filter()` isola o enquadramento. Futuro: estratégia com detecção/rastreamento de rosto e suavização da posição ao longo do tempo.
- Futuro: seleção semântica de melhores momentos; edição do texto das legendas; cancelamento de tarefas; progresso por frames; histórico persistente; limpeza automática de arquivos; fila com limites e autenticação antes de hospedagem pública.

Referências: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e [filtros FFmpeg](https://ffmpeg.org/ffmpeg-filters.html).


## Enquadramento manual: implementação e validação

Prévia: `object-fit: cover` e `object-position: p% 50%`. Exportação: escala pela proporção de exibição (`dar`), recorta em `x = round((largura escalada - 720) × p)` e centraliza verticalmente. A API aceita `position` de 0 a 1; ausência mantém 0,5. Valores fora do intervalo e não finitos são rejeitados. Legendas são aplicadas depois do recorte. Diferenças subpixel de rasterização e compressão entre navegador e H.264 são normais; o campo visual usa a mesma geometria.

Validação: 15 exportações reais (esquerda/centro/direita em paisagem, quadrado, 9:16, estreito e pixels não quadrados), comparadas com a geometria independente de `cover`; exportação adicional com legenda. Controle e exportação verificados também na interface.

## Porta local e Render

Inicie com `python app.py`. Quando `PORT` estiver definida, ela tem prioridade e o servidor escuta em `0.0.0.0`, conforme exigido pelo Render. Sem `PORT`, continua em `127.0.0.1:8001`; `CORTAVIDEO_PORT` permite escolher outra porta local.

Esta alteração configura apenas a porta e o endereço de escuta; não constitui validação de deploy no Render. FFmpeg, modelo local, armazenamento e tratamento de origem HTTPS atrás do proxy ainda precisam ser configurados/validados para hospedagem.
