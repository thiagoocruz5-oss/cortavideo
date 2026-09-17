# CortaVídeo

## Render: modelo preparado automaticamente no build

`render.yaml` configura a instalação e a preparação automática do modelo. Para o serviço **já existente**, configure uma vez no painel:

- **Build Command:** `python -m pip install -r requirements.txt && python preparar_youtube.py && python preparar_modelo.py`
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
- Um processo separado transcreve blocos de até 60 segundos no modo de pouca memória (32 segundos no modo local padrão), com sobreposição e timestamps globais. Ao terminar, libera a memória do modelo. A divisão pode alterar palavras nas fronteiras dos blocos.
- Upload/análise/exportação compartilham uma única vaga de processamento; novas operações recebem uma mensagem para tentar depois quando ela está ocupada.
- FFmpeg usa uma thread por decodificador, filtro e codificador, sem lookahead na exportação. Logs ficam em disco; timeout e encerramento do servidor interrompem os subprocessos.
- Transcrições ficam em disco. Áudio temporário, legendas intermediárias e exports incompletos são removidos inclusive em falhas tratáveis. Arquivos de entrada e MP4 finais permanecem disponíveis e recebem limpeza por expiração (24 horas por padrão, configurável por `FILE_TTL_HOURS`). Um encerramento forçado pelo sistema pode impedir a limpeza imediata.
- O navegador trata respostas vazias, inválidas e falhas de conexão com uma mensagem compreensível.

**Validação:** 61 testes Python (incluindo FFmpeg real) e 20 testes JavaScript passaram. Um fluxo real passou por upload, transcrição `tiny`, legendas, enquadramento à direita, exportação 720×1280, HEAD, download parcial e limpeza temporária. Em uma transcrição real de 90 segundos, o processo do modelo teve pico residente de **269 MiB no Windows**. Essa medida não inclui todo o serviço e não certifica consumo abaixo de 512 MB no Linux/Render. Vídeos de resolução muito alta e buffers nativos ainda podem exceder esse limite; confirme o consumo no novo deploy. Use somente uma instância do servidor por serviço.

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

## Exportação mais rápida e ajuste de tempos

A exportação usa `libx264 -preset veryfast -crf 22 -tune zerolatency`, mantendo uma thread de decodificação, filtro e codificação. O corte já usava busca antes da entrada (`-ss` antes de `-i`) e uma única codificação; essas características foram preservadas. Não há carregamento do modelo de transcrição na exportação. Resolução, áudio AAC, enquadramento e legendas ASS permanecem iguais. O preset pode mudar a compressão e o tamanho do arquivo dependendo do conteúdo.

Comparação local no Windows, com vídeo sintético em movimento 1280×720/30 fps, corte de 50 segundos, saída 720×1280, áudio e legendas, uma execução sequencial por preset:

| Preset | Tempo | Pico residente do FFmpeg | MP4 |
| --- | ---: | ---: | ---: |
| fast (anterior) | 43,59 s | 81,0 MiB | 34,41 MiB |
| veryfast (adotado) | 17,00 s | 75,7 MiB | 33,13 MiB |
| superfast | 13,49 s | 75,7 MiB | 40,35 MiB |

Foi escolhido `veryfast` pelo equilíbrio entre velocidade e compressão. Esses números são uma comparação local, não uma previsão de tempo nem certificação de memória no Render. Fonte técnica: [opções de codificação e busca do FFmpeg](https://ffmpeg.org/ffmpeg-all.html).

Os campos Início e Fim aceitam segundos com ponto ou vírgula e podem ficar vazios durante a digitação. O texto não é reescrito a cada tecla. Os botões −5s, −1s, +1s e +5s respeitam os limites do vídeo e a ordem do intervalo. Uma entrada manual inválida mostra uma mensagem e bloqueia a exportação. Permanece a regra de cortes de 30 a 60 segundos. A duração é recalculada imediatamente; editar Início mostra seu primeiro instante e editar Fim mostra o instante imediatamente anterior ao fim. Qualquer ajuste invalida o resultado anterior. Controles ficam bloqueados durante a exportação.

Para incluir a validação real de FFmpeg na suíte (requer FFmpeg/ffprobe com libass), no PowerShell:

```powershell
$env:CORTAVIDEO_MEDIA_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_client.cjs
```

Sem a variável, o teste real de mídia é pulado. Ele verifica os três enquadramentos (esquerda, centro e direita), áudio, legendas gravadas, duração, resolução e remoção de legendas temporárias. Os testes de interface cobrem digitação, separadores decimais, limites, botões, bloqueio durante exportação e o envio dos tempos/enquadramento para a API.

## Transcrição com progresso e download resiliente

No modo `LOW_MEMORY_MODE=1` (padrão no Render), a leitura é de 56 segundos úteis por bloco, com até dois segundos de contexto de cada lado: **máximo de 60 segundos de áudio na RAM**. Antes eram 28 segundos úteis/32 com contexto. Isso reduz o número de chamadas, sobreposição e preparação de recursos por chamada. Não muda a janela interna de 30 segundos do Whisper. O áudio continua extraído uma única vez para WAV mono/16 kHz/int16 em disco. O modelo continua carregado uma única vez no processo isolado por vídeo, que termina antes da exportação; não há processo por bloco nem processamento em lote paralelo.

O perfil Render usa `beam_size=1`, `temperature=0` e `best_of=1`. Antes, mesmo com beam 1, a lista padrão de temperaturas podia executar novas tentativas e gerar cinco candidatos em trechos difíceis. A nova configuração elimina essas tentativas: melhora velocidade, mas pode reduzir a qualidade em fala difícil/ruidosa. VAD, timestamps por palavra, contexto e eliminação da sobreposição são mantidos. O Windows sem modo de pouca memória mantém o perfil anterior. O modelo `tiny`/int8 e uma thread permanecem; não use vários workers no Render gratuito.

O worker publica um pequeno arquivo JSON de progresso por bloco, substituído atomicamente. O servidor verifica mudanças uma vez por segundo, sem importar Whisper, e a interface mostra `Transcrevendo bloco 3 de 10`. O número concluído só avança ao finalizar um bloco. Extração e carregamento do modelo têm mensagens próprias; um bloco em andamento pode demorar na CPU compartilhada.

### Download

O resultado da API mantém `url` para prévia e acrescenta `download_url` com `?download=1`. O botão **Baixar vídeo** verifica o MP4 por HEAD e inicia download nativo, sem carregar o arquivo em um Blob no navegador. O endpoint usa `Content-Disposition: attachment`, tamanho exato, ETag, Range e If-Range para retomada. GET da prévia continua sem disposição de anexo.

O arquivo é aberto antes de enviar headers, transferido em buffers de 256 KiB e protegido contra limpeza enquanto a resposta está ativa. Ao terminar ou interromper, sua retenção é renovada. Saturação das oito conexões passa a responder 503/Retry-After em vez de encerrar silenciosamente. Erros depois dos headers são registrados, sem tentar enviar JSON dentro do MP4. A consulta do progresso repete somente GETs em falhas transitórias, até três vezes; POSTs não são repetidos automaticamente.

Um download nativo pode falhar depois da verificação HEAD; a página não tem acesso ao resultado final do gerenciador de downloads do Chrome. Nesse caso, use **Retomar** no navegador ou Baixar vídeo novamente. Isso funciona enquanto o mesmo arquivo existe. Se houver reinício/redeploy, o disco temporário do Render pode desaparecer e será necessário reenviar/exportar. Nenhuma correção HTTP consegue recuperar um arquivo perdido sem armazenamento persistente externo.

Para diagnóstico, os logs agora registram `DOWNLOAD complete`, `TRANSFER interrupted` (bytes enviados e motivo), PID/início do servidor e `SHUTDOWN` quando há SIGTERM. Compare com eventos de memória/reinício do Render. Um encerramento forçado por falta de memória pode impedir qualquer log final. O erro “Rede desconectada” sozinho não prova OOM nem exclusão do arquivo. Foram identificados riscos no código, mas a causa da ocorrência anterior depende desses registros.

Referências: [opções do faster-whisper](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py), [recursos do Render](https://render.com/docs/compute-plans) e [disco temporário/reinícios](https://render.com/docs/faq).


### Medição desta otimização

Em duas execuções sequenciais com o mesmo áudio de fala de 90 segundos, `tiny`/int8, no Windows: antes **61,13 s / 58,33 s**, depois **13,00 s / 13,03 s**. Pico residente do worker: antes **268,1–268,8 MiB**, depois **243,0–243,1 MiB**. Ambos produziram 181 palavras nessa amostra; isso não substitui avaliação de precisão com outros áudios. O ganho varia com fala, ruído e CPU. Não é medição do serviço completo no Render nem garantia absoluta de 512 MB.

Validação atual: 61 testes Python com o teste de mídia habilitado e 20 JavaScript, além de upload/transcrição/exportação/download HTTP reais. Foram testados progresso por bloco, carga única do modelo, limite da janela, download completo e parcial, cliente desconectado seguido de retomada, proteção contra limpeza, arquivo ausente, saturação e falhas de rede/timeout na interface.


## Importar do YouTube

Na tela inicial, escolha **Selecionar vídeo** ou cole um link em **Colar link do YouTube** e clique em **Importar vídeo**. O título, a duração e as etapas aparecem durante o processamento. O editor abre quando a mídia local e a transcrição estão prontas. A prévia usa o MP4 do servidor, sem player incorporado do YouTube. Além dos controles de corte, há uma barra de navegação e botões para avançar/voltar cinco segundos.

### Instalação adicional

Instale **Node.js 22 ou superior** (https://nodejs.org/) e atualize as dependências Python. No Windows:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe preparar_youtube.py
.\.venv\Scripts\python.exe app.py
```

No Render, mantenha `WHISPER_MODEL=tiny` e `LOW_MEMORY_MODE=1`, configure `NODE_VERSION=22.22.0` e use:

- Build: `python -m pip install -r requirements.txt && python preparar_youtube.py && python preparar_modelo.py`
- Start: `python app.py`

Preserve as etapas de instalação de FFmpeg/ffprobe já existentes. `render.yaml` inclui essas configurações, mas serviços criados manualmente precisam ser atualizados no painel. `preparar_youtube.py` verifica Node e os pacotes, sem baixar vídeos. O yt-dlp/EJS está fixado na versão testada em requirements.txt; atualize essa dependência e rode os testes se mudanças do YouTube exigirem uma versão nova.

### Velocidade, qualidade e memória

- O yt-dlp roda em processo separado, com download sequencial direto para disco, buffer de 64 KiB, limite total de 1 GiB e verificações de espaço livre. Não carrega o vídeo inteiro na memória.
- Apenas links de vídeos individuais são aceitos. Metadados são obtidos uma vez; as URLs das faixas são reutilizadas na mesma importação.
- Seleciona H.264/MP4 e AAC/M4A, entre 720 e 1080 pixels no lado menor, no máximo 1920 no lado maior. Prefere 30 fps quando existe na resolução escolhida, aceitando até 60 fps. Não baixa 4K nem escolhe silenciosamente 360p. Se não houver formato compatível, mostra erro e mantém a alternativa de upload.
- Baixa áudio primeiro e vídeo depois, uma vez cada. Se o formato já contém áudio, baixa somente esse arquivo. FFmpeg junta as faixas com `-c copy`, sem recodificação, e prepara o MP4 para reprodução progressiva. A recodificação ocorre apenas na exportação do corte.
- O download termina antes de iniciar Whisper. A faixa de áudio separada alimenta a conversão única mono/16 kHz e a transcrição existente em blocos limitados. Não há downloader e modelo carregados simultaneamente. Node recebe limite de heap de 96 MiB; esse limite não corresponde ao consumo total de todos os processos.
- Uma única vaga de processamento pesado é compartilhada entre upload, importação e exportação. Uma importação concluída do mesmo link é reutilizada enquanto a tarefa e os arquivos existem nesta instância.
- O arquivo original de vídeo separado é removido depois da montagem do MP4; o áudio separado é removido depois da análise. Em erro, a pasta da importação é removida. Não se armazenam miniaturas, dumps completos de metadados nem outra cópia de preview.
- Source e exports seguem a retenção de 24 horas configurável por `FILE_TTL_HOURS`. Exports antigos também expiram individualmente. A limpeza não remove arquivos de pastas com transferências ativas. Downloads renovam o acesso sem alterar o ETag, preservando a retomada.
- No Linux os subprocessos usam grupos próprios, permitindo encerrar filhos como Node em timeout/encerramento. No Windows permanece o encerramento da árvore de processos. O download tem limite de 30 minutos, socket de 20 segundos e poucas tentativas. A API responde com o identificador da tarefa imediatamente, sem manter a requisição de importação aberta até terminar.

### Segurança e limitações práticas

Aceita `youtube.com/watch`, `youtu.be`, `/shorts/` e `/embed/` com ID válido; normaliza para uma URL HTTPS de vídeo individual e descarta parâmetros adicionais. Rejeita domínios semelhantes, credenciais, portas personalizadas, arquivos locais, playlists e URLs arbitrárias. Apenas o extrator YouTube é registrado. O worker limita destinos HTTPS, verifica redirecionamentos pelo transporte Urllib e bloqueia conexões a IPs privados/locais. Os subprocessos recebem argumentos separados, sem concatenar comandos de shell. Não usa cookies, login, proxies ou mecanismos para contornar restrições.

O YouTube pode bloquear IPs de datacenter, exigir autenticação ou não oferecer os formatos selecionados. Um link que funciona no navegador pessoal pode falhar no Render. Lives, vídeos privados, restritos, removidos ou sem formatos compatíveis não são importados. Nesses casos, o aplicativo informa o problema e oferece o upload tradicional.

O Render gratuito possui CPU limitada e disco temporário. Reinícios/redeploys podem apagar mídia, tarefas e resultados. O download, a montagem e a extração precisam de espaço em disco, inclusive uma cópia temporária durante o remux. As verificações reduzem falhas, mas não reservam disco contra outros processos. Preview e download final consomem tráfego de saída. Não há garantia de tempo de processamento ou certificação de todo o serviço sob 512 MB no Render; valide o consumo após publicar. Mantenha a página aberta para acompanhar o trabalho. Um encerramento forçado pode impedir a limpeza imediata.

Referências: [yt-dlp/EJS e runtimes](https://github.com/yt-dlp/yt-dlp/wiki/EJS), [Node no Render](https://render.com/docs/node-version), [Render gratuito](https://render.com/docs/free).

### Validação da importação

A suíte usa mocks/fixtures para não depender do YouTube: URLs e domínios, metadados, seleção de qualidade, falhas, espaço livre, arquivos temporários, reutilização, transcrição da faixa importada, preview, controles de tempo, exportação e download. Com `CORTAVIDEO_MEDIA_TESTS=1`, a integração usa servidor HTTP e FFmpeg reais, com transporte YouTube e texto de transcrição controlados.

Também foi realizado um download real independente: vídeo público de 635 segundos, H.264 1080p com AAC, cerca de 268 MB, importado e montado em 41,1 segundos no Windows. Esse teste verificou mídia completa com áudio; não mede a duração da transcrição nem prevê a velocidade no Render. Os arquivos desse teste foram removidos.

Resultado final desta versão: **78 testes Python e 24 JavaScript passaram**, com os testes reais de FFmpeg habilitados.

### Diagnóstico de importação no Render

O build imprime as versões de yt-dlp, EJS e Node. Cada importação registra no servidor os avisos e o diagnóstico detalhado do yt-dlp, formatos selecionados e traceback em caso de falha. Os registros do subprocesso ficam em disco durante a operação e são repassados ao log do servidor ao terminar, inclusive quando falha, em blocos de até 8 KiB. URLs assinadas e credenciais são ocultadas; o diagnóstico técnico não é enviado à interface.

O aplicativo executa `python youtube_worker.py URL_CANONICA PASTA_TEMPORARIA` como lista de argumentos, sem shell. O worker usa a API `YoutubeDL.extract_info(..., download=False, process=False, ie_key='Youtube')` uma vez e `process_info(track)` para baixar cada faixa. O FFmpeg apenas junta as faixas com `-c copy -movflags +faststart`. Não há cookies pessoais, proxy ou login.

Se houver falha, copie os registros `YouTube [identificador]` da mesma importação. Uma resposta explícita de confirmação de bot ou HTTP 429 indica bloqueio/limitação de acesso automatizado. HTTP 403 sozinho não demonstra que o IP do Render foi bloqueado. Compare as versões impressas no build com o ambiente local; o arquivo render.yaml só configura automaticamente serviços vinculados ao Blueprint.

Teste controlado local em 17/09/2026, antes da alteração dos logs: link LN4dE1W9X0U, usando `youtube_import.obtain` e o worker real, sem mocks no download. Download e remux concluídos em 34 s, arquivo de 414.036.466 bytes, duração de 1.336,77 s e áudio presente. Os arquivos do teste foram removidos ao encerrar. Esse resultado não mede nem garante acesso a partir do Render; a causa da falha remota depende dos registros dessa instância.

### Proteção de rede do importador

A URL inicial continua limitada a links individuais do YouTube. No worker isolado, os destinos HTTPS podem pertencer às famílias youtube.com, youtube-nocookie.com, googlevideo.com, ytimg.com, google.com, googleapis.com, gstatic.com, ggpht.com e googleusercontent.com, incluindo subdomínios. A comparação respeita limites de domínio (google.com.evil.test não é aceito). Não há liberação genérica de destinos externos.

Cada requisição/redirecionamento via urllib é validado. Credenciais na URL, portas diferentes de 443 e protocolos não HTTPS são recusados. Na conexão, o endereço IP efetivo precisa ser público: localhost, redes privadas, link-local, metadata, multicast e IPv6 interno continuam bloqueados mesmo quando um nome autorizado resolve para esses endereços. O transporte permanece urllib, sem proxies ou transportes que ignorem essa verificação.

Uma recusa gera `YouTube network denied hostname=... reason=...`, sem caminho ou parâmetros da URL. O erro antigo não incluía hostname, portanto não permite identificar retroativamente qual destino o Render recusou. A ampliação das famílias corrige a limitação da lista antiga; uma eventual recusa remota restante exige o novo registro para identificar o destino, sem liberar domínios arbitrariamente.

### Falha `Failed to extract any player response`

Esse erro é emitido pelo yt-dlp quando nenhuma resposta utilizável do player foi obtida; ocorre antes da escolha de formato, download e FFmpeg. Não demonstra, sozinho, falta de memória, bloqueio de IP ou incompatibilidade do Python. Verifique os avisos anteriores no log: agora são classificados como player_extraction, http_error, rate_limit, authentication_or_restriction, unavailable, network ou memory. Código de saída 1 e SIGKILL não são classificados automaticamente como memória; é necessária indicação explícita do processo.

Mantemos clientes padrão do yt-dlp (visionos/web na versão 2026.8.19), extractor_args e headers padrão, resolução IPv4/IPv6 do sistema e Node habilitado para EJS. Não são adicionados cookies, autenticação, proxies ou clientes alternativos para contornar restrições. O Build Command com preparar_youtube.py verifica a versão instalada contra requirements.txt e imprime Python, yt-dlp, EJS e Node. Os logs de importação mostram versões e configuração efetiva.

O pacote yt-dlp 2026.8.19 declara suporte a Python 3.14. A aplicação completa foi testada localmente em Python 3.12.10; não foi validado todo o conjunto de dependências em Python 3.14 no Render. Incluímos .python-version com 3.12 para alinhar serviços que não usam Blueprint à família já prevista pelo projeto. No Render, PYTHON_VERSION definido no painel tem prioridade sobre esse arquivo; confira essa variável se o build continuar usando 3.14. Isso alinha ambientes, mas não constitui correção comprovada da extração do player.

Teste local controlado do link qDLsG-_SuQI: extração com o worker e política de rede reais concluída, duração 1543 segundos, formatos 137/140 disponíveis, Node detectado como provedor JS. O teste parou antes do download para isolar a etapa que falhou no Render. Sem os avisos anteriores e as versões impressas pelo deploy remoto, não é possível atribuir a falha remota a uma causa específica.
