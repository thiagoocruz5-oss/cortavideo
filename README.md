# CortaVídeo

## Render: modelo preparado automaticamente no build

`render.yaml` configura a instalação e a preparação automática do modelo. Para o serviço **já existente**, configure uma vez no painel:

- **Build Command:** `python -m pip install -r requirements.txt && python preparar_modelo.py`
- **Start Command:** `python app.py`
- **WHISPER_MODEL:** `tiny`, igual no build e na execução.
- **LOW_MEMORY_MODE:** `1`. Se o serviço existente ainda tiver `WHISPER_MODEL=base`, altere para `tiny` no painel.
- **Root Directory:** pasta que contém `app.py` e `preparar_modelo.py` (vazio se estiverem na raiz).

Se seu Build Command já instala FFmpeg/ffprobe, preserve essas etapas e apenas acrescente `&& python preparar_modelo.py` ao final. O Blueprint não instala os executáveis FFmpeg. Adicionar `render.yaml` não reconfigura automaticamente um serviço criado manualmente: ele é usado por serviços gerenciados como Blueprint. Não é necessário criar outro serviço. Em Docker, inclua `RUN python preparar_modelo.py` depois de copiar o projeto e instalar dependências, mantendo `models/` na imagem final.

Faça um novo deploy após enviar os arquivos. O modelo fica no artefato do build, disponível no início da aplicação, sem download durante uploads. Arquivos completos existentes são reutilizados e validados. Download incompleto ou erro de carregamento interrompem o build; `.ready` só é gravado após sucesso. O funcionamento local no Windows continua igual.

### Memória no Render gratuito

A transcrição continua usando **faster-whisper em CPU/int8**. No Render, o padrão agora é `tiny`; no Windows local, continua `base`. Uma configuração explícita de `WHISPER_MODEL` tem prioridade. O modelo `tiny` consome menos memória, com possível perda de precisão.

O upload já era gravado em blocos de 1 MiB. O principal risco identificado estava depois: decodificação do áudio inteiro e modelo carregado no processo permanente do servidor. Duas horas de áudio float32/16 kHz representam cerca de 439 MiB, sem contar modelo e servidor. Sem métricas do deploy anterior, não é possível determinar a etapa exata em que o Render encerrou o serviço.

Agora:

- FFmpeg extrai áudio para um arquivo temporário em disco e termina antes de carregar o modelo.
- Um processo separado transcreve blocos de até 32 segundos, com sobreposição e timestamps globais. Ao terminar, libera a memória do modelo. A divisão pode alterar palavras nas fronteiras dos blocos.
- Upload/análise/exportação compartilham uma única vaga de processamento; novas operações recebem uma mensagem para tentar depois quando ela está ocupada.
- FFmpeg usa uma thread por decodificador, filtro e codificador, sem lookahead na exportação. Logs ficam em disco; timeout e encerramento do servidor interrompem os subprocessos.
- Transcrições ficam em disco. Áudio temporário, legendas intermediárias e exports incompletos são removidos inclusive em falhas tratáveis. Arquivos de entrada e MP4 finais permanecem disponíveis e recebem limpeza por expiração (24 horas por padrão, configurável por `FILE_TTL_HOURS`). Um encerramento forçado pelo sistema pode impedir a limpeza imediata.
- O navegador trata respostas vazias, inválidas e falhas de conexão com uma mensagem compreensível.

**Validação:** 45 testes Python e 6 testes JavaScript passaram. Um fluxo real passou por upload, transcrição `tiny`, legendas, enquadramento à direita, exportação 720×1280, HEAD, download parcial e limpeza temporária. Em uma transcrição real de 90 segundos, o processo do modelo teve pico residente de **269 MiB no Windows**. Essa medida não inclui todo o serviço e não certifica consumo abaixo de 512 MB no Linux/Render. Vídeos de resolução muito alta e buffers nativos ainda podem exceder esse limite; confirme o consumo no novo deploy. Use somente uma instância do servidor por serviço.

O disco do Render gratuito é temporário: reinícios podem perder uploads e exports. O modelo preparado no build acompanha o artefato. Referência: [limitações gratuitas do Render](https://render.com/docs/free).

MVP local para transformar um MP4 em cortes verticais de 30 a 60 segundos. Interface em português, transcrição real com faster-whisper, sugestões por densidade de fala e finais de frases, ajuste de intervalo, prévia com enquadramento horizontal, legendas opcionais e exportação com FFmpeg.

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
- Arquivos ficam em `data/`, com limpeza automática por expiração. O histórico das tarefas existe apenas em memória e expira após 24 horas por padrão: ao reiniciar ou expirar, reenvie o vídeo.
- Sem `PORT`, o servidor escuta em `127.0.0.1`. No Render, usa `PORT` e `0.0.0.0`. A proteção de origem não substitui autenticação; o MVP não possui contas de usuário.

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
node tests/test_client.cjs
```

Na lista de filtros, confira `subtitles`. Se faltar, instale uma distribuição do FFmpeg com libass. Se o navegador não reproduzir o MP4 original, ele pode usar um codec não suportado pelo navegador; tente a exportação, que converte para H.264. Erros de download do Whisper normalmente pedem verificar internet, proxy ou espaço em disco. Para encerrar o servidor, pressione Ctrl+C.

## Organização e próximas melhorias

- `app.py`: servidor, upload em blocos, fila e download com suporte a intervalos.
- `processing.py`: coordenação da transcrição, sugestões, legendas e FFmpeg.
- `transcription_worker.py`: modelo isolado e áudio em blocos.
- `process_runner.py`: subprocessos, logs em disco e timeout.
- `runtime_config.py`: seleção consistente do modelo no build e na execução.
- `static/`: interface responsiva sem dependências de frontend.
- `processing.framing_filter()` isola o enquadramento. Futuro: estratégia com detecção/rastreamento de rosto e suavização da posição ao longo do tempo.
- Futuro: seleção semântica de melhores momentos; edição do texto das legendas; cancelamento de tarefas; progresso por frames; histórico persistente; autenticação e cotas por usuário.

Referências: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) e [filtros FFmpeg](https://ffmpeg.org/ffmpeg-filters.html).


## Enquadramento manual: implementação e validação

Prévia: `object-fit: cover` e `object-position: p% 50%`. Exportação: escala pela proporção de exibição (`dar`), recorta em `x = round((largura escalada - 720) × p)` e centraliza verticalmente. A API aceita `position` de 0 a 1; ausência mantém 0,5. Valores fora do intervalo e não finitos são rejeitados. Legendas são aplicadas depois do recorte. Diferenças subpixel de rasterização e compressão entre navegador e H.264 são normais; o campo visual usa a mesma geometria.

Validação: 15 exportações reais (esquerda/centro/direita em paisagem, quadrado, 9:16, estreito e pixels não quadrados), comparadas com a geometria independente de `cover`; exportação adicional com legenda. Controle e exportação verificados também na interface.

## Porta local e Render

Inicie com `python app.py`. Quando `PORT` estiver definida, ela tem prioridade e o servidor escuta em `0.0.0.0`, conforme exigido pelo Render. Sem `PORT`, continua em `127.0.0.1:8001`; `CORTAVIDEO_PORT` permite escolher outra porta local.

Esta alteração configura apenas a porta e o endereço de escuta; não constitui validação de deploy no Render. FFmpeg, modelo local, armazenamento ainda precisam ser configurados/validados para hospedagem.

### Proteção de origem

POSTs com `Origin` aceitam explicitamente `https://cortavideo.onrender.com`. Acesso HTTP local permite `127.0.0.1` e `localhost` quando o Host também é local e a porta coincide. Outros domínios, origem `null`, sufixos parecidos e portas diferentes são bloqueados. Cabeçalhos `X-Forwarded-*` não ampliam essa permissão. Clientes sem Origin mantêm a compatibilidade anterior; essa verificação não substitui autenticação.
