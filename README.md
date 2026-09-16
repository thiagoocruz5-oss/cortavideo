# CortaVídeo

## Render: modelo preparado automaticamente no build

`render.yaml` configura a instalação e a preparação automática do modelo. Para o serviço **já existente**, configure uma vez no painel:

- **Build Command:** `python -m pip install -r requirements.txt && python preparar_modelo.py`
- **Start Command:** `python app.py`
- **WHISPER_MODEL:** `base`, igual no build e na execução.
- **Root Directory:** pasta que contém `app.py` e `preparar_modelo.py` (vazio se estiverem na raiz).

Se seu Build Command já instala FFmpeg/ffprobe, preserve essas etapas e apenas acrescente `&& python preparar_modelo.py` ao final. O Blueprint não instala os executáveis FFmpeg. Adicionar `render.yaml` não reconfigura automaticamente um serviço criado manualmente: ele é usado por serviços gerenciados como Blueprint. Não é necessário criar outro serviço. Em Docker, inclua `RUN python preparar_modelo.py` depois de copiar o projeto e instalar dependências, mantendo `models/` na imagem final.

Faça um novo deploy após enviar os arquivos. O modelo fica no artefato do build, disponível no início da aplicação, sem download durante uploads. Arquivos completos existentes são reutilizados e validados. Download incompleto ou erro de carregamento interrompem o build; `.ready` só é gravado após sucesso. O funcionamento local no Windows continua igual.

### Memória: 512 MB não garantem transcrição

Preservamos faster-whisper, modelo multilíngue `base`, CPU e `int8`. Um teste real com áudio curto no Windows mediu pico residente de **312,8 MiB** e pico de memória comprometida de **1492,8 MiB**. Essas métricas não são equivalentes ao consumo de um container Linux. Não foi feito teste sob limite real de 512 MB no Render.

A implementação decodifica todo o áudio antes de transcrever: duas horas de mono float32 a 16 kHz representam cerca de **439 MiB só de áudio**, além do modelo, VAD, buffers e servidor. Assim, o limite de duas horas do upload não significa que o plano gratuito suporte esse processamento. Mesmo vídeos curtos podem ultrapassar a memória disponível; nesse caso, o Render pode encerrar o processo. A preparação automática resolve o modelo ausente, não a falta de RAM.

A fila continua com uma tarefa por vez. Para confiabilidade, meça no Linux com vídeos reais e use uma instância com memória suficiente; processamento do áudio em blocos é uma possível melhoria futura. `tiny` é uma opção explícita de WHISPER_MODEL com menor precisão, mas não foi adotada nem certificada para 512 MB. Não use `small` esperando caber nesse limite.

O plano gratuito suspende serviços ociosos após 15 minutos, pode reiniciá-los e não oferece disco persistente. Uploads, exports e tarefas em memória podem se perder. O modelo incluído no build volta com o artefato; arquivos criados durante a execução não têm essa garantia. O build precisa de acesso ao Hugging Face e consome minutos de build para baixar o modelo.

Referências: [limitações gratuitas](https://render.com/docs/free) e [recursos dos planos](https://render.com/docs/compute-plans).

Validação: **33 testes passaram**, incluindo download simulado, reutilização, arquivos incompletos e falha de validação sem marcador de sucesso. A validação do modelo local e uma transcrição real com timestamps também passaram. O deploy no Render e o limite real de 512 MB ainda não foram testados.

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

Esta alteração configura apenas a porta e o endereço de escuta; não constitui validação de deploy no Render. FFmpeg, modelo local, armazenamento ainda precisam ser configurados/validados para hospedagem.

### Proteção de origem

POSTs com `Origin` aceitam explicitamente `https://cortavideo.onrender.com`. Acesso HTTP local permite `127.0.0.1` e `localhost` quando o Host também é local e a porta coincide. Outros domínios, origem `null`, sufixos parecidos e portas diferentes são bloqueados. Cabeçalhos `X-Forwarded-*` não ampliam essa permissão. Clientes sem Origin mantêm a compatibilidade anterior; essa verificação não substitui autenticação.
