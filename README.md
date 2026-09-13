# Planetary Image Studio

## Duplicatas exatas

Use **Ferramentas → Remover duplicatas…**, escolha pasta/SOL atual ou missão inteira e clique em **Buscar duplicatas**. A busca compara todos os pixels decodificados, com dimensões, profundidade de bits, transparência, orientação EXIF e perfil ICC compatíveis. Não usa miniaturas, tolerância ou semelhança visual. Um hash seleciona candidatos, seguido de confirmação dos bytes. Diferenças de um pixel são mantidas; imagens com múltiplos quadros ou leitura incompleta são mantidas e informadas.

Revise os grupos: cada grupo mostra a imagem mantida, as cópias removíveis com caixas de seleção e as protegidas. **Qualquer arquivo `.annotations.json` protege a imagem**, mesmo vazio, ilegível ou contendo apenas histórico. A imagem aberta e documentos pendentes também são protegidos. Várias cópias anotadas são todas mantidas. A busca não exclui nada: a exclusão permanente ocorre somente ao clicar em **Excluir cópias selecionadas**, com downloads pausados. Pixels e proteção são revalidados antes de excluir.

Os caminhos relativos removidos e a cópia mantida ficam em **`.duplicate_registry.json`**, na raiz da missão, gravado antes da exclusão. Curiosity, Perseverance e os acervos consultam esse registro ao baixar novamente. O bloqueio vale para aquele caminho da missão e somente enquanto a cópia mantida continuar existindo com o mesmo conteúdo de pixels. Se ela desaparecer, mudar ou o registro ficar ilegível, o download é liberado para permitir recuperação. Conserve esse registro ao mover a coleção. Metadados auxiliares `.source.json` permanecem disponíveis; o arquivo original mantido não é regravado.

## Remover imagens em preto e branco

Use **Ferramentas → Remover imagens em preto e branco…**, escolha pasta/SOL atual ou missão inteira e clique em **Buscar imagens em preto e branco**. Revise a lista, desmarque o que quiser manter e clique em **Excluir imagens selecionadas**. A busca não exclui arquivos; a exclusão é permanente e acontece somente pelo botão.

A detecção verifica todos os pixels do arquivo original, preservando a profundidade de bits. Imagens grayscale e RGB com canais exatamente iguais são candidatas. Qualquer diferença entre os canais mantém a imagem, inclusive um único pixel: fotografias quase cinza, mas com alguma cor, não são removidas. Esta verificação é mais conservadora que a amostragem do filtro **Coloridas**. Ajustes de saturação e overlays não interferem. Arquivos ilegíveis ou com múltiplos quadros são mantidos.

Imagens com arquivo de anotações (mesmo vazio ou ilegível), edições em memória e a imagem aberta ficam protegidas. Antes de excluir, a ferramenta confere novamente os pixels e as anotações. Os nomes relativos à missão são registrados em `.duplicate_registry.json` antes da exclusão, com motivo `black_and_white`. Curiosity, Perseverance e os conectores de arquivos ignoram esses nomes nos próximos downloads, mesmo sem outra cópia. O registro também cobre duplicatas cuja cópia mantida tenha sido posteriormente removida por esta ferramenta. Excluir a entrada do registro permite baixar aquele nome novamente. Metadados auxiliares e anotações não são apagados.

## Baixar novamente imagens removidas

Use **Ferramentas → Baixar imagens removidas automaticamente** para restaurar as imagens removidas por duplicidade ou por serem preto e branco **na missão atual**. O comando apaga `.duplicate_registry.json`, liberando os nomes para download, e abre o painel de download existente. Ele consulta os catálogos de origem e solicita apenas os nomes registrados. Arquivos já presentes, anotações, `.source.json` e o cursor do acervo são preservados. Não é necessário recomeçar todos os SOLs nem percorrer os lotes anteriores do acervo.

A lista de restauração é salva na sessão antes de apagar o registro. **Parar/Continuar** permite retomar após interrupções ou falhas; imagens indisponíveis no catálogo são informadas como pendentes. Se já houver um download em andamento, pause-o antes de executar o comando. A opção só fica disponível em missões que oferecem download automático.

## Perfis de ajustes

A barra **Perfis de ajustes** oferece três slots fixos: **Perfil 1**, **Perfil 2** e **Perfil 3**, cada um com um botão **Salvar** ao lado. Ajuste a imagem e clique em Salvar no slot desejado; clique no nome do perfil para aplicar em outra imagem. Salvar novamente substitui aquele slot sem pedir nome. Perfis vazios ficam indisponíveis para aplicação; o botão do perfil fica destacado quando os ajustes atuais coincidem com os valores salvos.

São gravados brilho, contraste, cor/saturação, meios-tons/gamma, preto, branco, nitidez, suavização, inversão, equilíbrio de cores, ativação e limites dos percentis e ativação do Auto Enhance. Aplicar atualiza os controles deslizantes, valores e botões, com uma única entrada no histórico para Desfazer/Refazer. Os perfis são globais, persistem entre reinicializações e missões e não são apagados por Resetar ajustes. Rotação, zoom, seleções e desenhos da imagem atual são preservados; não fazem parte dos perfis. Salvar um perfil não aplica processamento a outras imagens nem altera o arquivo original.

## Auto Enhance Mars Image

Use **Imagem / Auto Enhance Mars Image** para aplicar automaticamente o preset aprovado: **Percentis RGB 32-99 sobre o original limpo**. Com os demais filtros desligados, o resultado e identico ao botao manual de percentis configurado em 32 e 99. Nao ha correcao de iluminacao, recoloracao, CLAHE ou mistura posterior neste preset. Os auxiliares dessas operacoes continuam no modulo, mas nao participam do automatico.

A mascara e exatamente a da ferramenta manual: max(R,G,B)>5 e alfa>0. Pixels quase pretos e transparentes nao entram nas estatisticas; bordas cinzentas ainda podem entrar. A mascara circular conservadora nao e usada neste preset porque mudaria os cortes e o resultado aprovado. O percentil 32 leva os valores abaixo desse corte a zero por canal. Os valores 32-99 sao fixos no preset e independentes dos controles da ferramenta manual.

Original em disco, desenhos, zoom, Undo/Redo e Reset continuam no fluxo existente. Os filtros manuais ativos sao aplicados depois do automatico. Deixe o percentil manual desligado ao usar este preset para evitar duas expansoes consecutivas.

**Imagem / Salvar etapas do Auto Enhance** continua exportando oito PNGs e parameters.json para uma pasta nova. Por compatibilidade, os nomes antigos permanecem: illumination_corrected e o original; white_balance e final_clahe repetem o resultado dos percentis. O mapa illumination e o NPY contem zeros, identificados nos metadados como placeholders de uma etapa desativada. A exportacao usa o original limpo, sem desenhos ou ajustes manuais.

Testes: `python -m unittest test_auto_enhance_mars test_percentile_stretch`.

## Expansão por Percentis (Percentile Stretch)

Use **Imagem → Expansão por Percentis (Percentile Stretch)**, o menu do botão direito ou o botão na barra **Percentis**. O ajuste é aplicado imediatamente na imagem principal, inicialmente com **1% e 99%**, sem outro visualizador. O botão liga/desliga o ajuste. Os controles **Percentil inferior** e **Percentil superior** na mesma barra permitem alterar os limites; ao ajustá-los, a expansão é ativada. Sempre é mantido `0 ≤ inferior < superior ≤ 100`.

Cada canal RGB recebe `(pixel − p_low) × 255 / (p_high − p_low)`, com clipping e arredondamento para 8 bits. Pixels do original com todos os canais ≤ 5, ou alfa zero, são excluídos do cálculo dos percentis. A transformação é aplicada normalmente à imagem; o alfa é preservado. Se não houver pixels válidos, o ajuste não modifica o resultado; canais sem variação entre os percentis permanecem inalterados. A máscara é obtida do original, para que inversão/brilho não transformem uma borda inválida em uma amostra válida.

O ajuste integra `apply_adjustments()` após os outros ajustes de pixels e antes das marcações/rotação, usando a imagem de trabalho resultante. Não acumula novas expansões a cada renderização. Parâmetros e ativação usam o histórico de anotações existente, com **Desfazer/Refazer**, restauração por imagem, **Comparar original**, cópia/exportação final e filtro **Editadas**. **Resetar ajustes** desativa a expansão e restaura 1–99. Executar o ajuste nunca sobrescreve o arquivo original; o estado é salvo no arquivo de anotações, como nos demais filtros. Testes: `python -m unittest test_percentile_stretch -v`.

## Varinha mágica — seleção por tolerância

Abra **Análise → Varinha mágica**, pressione **V** ou use o ícone de varinha na barra **Desenho**, junto do lápis e do oval. Clique dentro da figura na prévia e ajuste **Tolerância (0–255)**. Azul mostra a seleção conectada ao ponto clicado. Em **Cor RGB**, cada canal pode diferir do pixel inicial até a tolerância escolhida; em **Luminosidade**, a comparação usa grayscale. **Conectar diagonais** troca a vizinhança de quatro para oito conexões. A referência é sempre o pixel inicial, evitando que uma sequência de pequenas diferenças avance indefinidamente por um gradiente.

Uma tolerância baixa seleciona uma faixa restrita de cor; aumentá-la inclui mais variação nos pixels conectados. A varinha usa o original, sem ajustes ou desenhos, mantém a rotação na prévia e funciona offline, sem IA ou reconhecimento de figuras. Se figura e fundo têm cores semelhantes ou estão conectados, a seleção pode atravessar esse limite: confira a prévia antes de aplicar. **Cancelar** não cria marcação.

**Criar marcação** converte o resultado em contornos fechados do sistema de anotações existente, incluindo vazios internos. O contorno fica selecionado e pode ser movido, redimensionado, excluído, salvo e desfeito/refeito; em seguida use **Morphological Analysis · Área marcada**. A conversão dos pixels para contornos editáveis pode diferir aproximadamente um pixel nas bordas. Os dados usam o tipo `polygon`, com pontos e comprimentos dos anéis no mesmo arquivo `.annotations.json`. Nenhum pixel original é alterado. Cálculo em `magic_wand.py`, prévia em `magic_wand_ui.py`; teste específico: `python -m unittest test_magic_wand -v`.

## Fase 2 — Análise morfológica da área marcada

Desenhe uma elipse, retângulo ou um limite com lápis, ou use **Selecionar área**. Abra **Análise → Morphological Analysis · Área marcada**, também na barra Análise. Sem uma marcação que contenha uma área válida, a ferramenta mostra **“Marque primeiro a área que deseja analisar.”** Não há seleção automática da imagem inteira.

A ferramenta reaproveita `AnnotationDocument.state["drawings"]`, a seleção ativa e o retângulo de seleção existentes. A marcação selecionada tem prioridade; na ausência dela, usa a seleção de área atual ou a última marcação válida. O seletor da janela permite escolher outra marcação existente e analisá-la. Textos, pontos, linhas sem interior, áreas externas à imagem e máscaras muito pequenas não são entradas válidas. O lápis é fechado com um segmento entre início e fim; essa aproximação é indicada no nome da marcação. Círculos antigos continuam usando centro e raio; elipses e retângulos usam seus dois cantos. A seleção de área é convertida da visualização rotacionada para as coordenadas originais.

A região em análise permanece contornada em **ciano**. A janela exibe a imagem original com a rotação atual, sem filtros/desenhos incorporados aos pixels analisados. Contorno estimado, bordas internas, fissuras candidatas, cavidades/regiões escuras, eixo principal, concavidades, saliências candidatas e estruturas/divisões internas têm controles independentes de sobreposição. **Resumo da forma** aparece primeiro; **Detalhes técnicos** é recolhível. Processamento em segundo plano com cancelamento; os desenhos, seus arquivos, desfazer/refazer e os filtros não são alterados.

`morphological_region_ui.py` usa `drawing_shape()` da seleção existente para rasterizar a máscara; `MorphologicalRegionAnalyzer` em `morphological_region_analyzer.py` recebe apenas RGB uint8 + máscara. Os cálculos usam OpenCV/NumPy e somente pixels da área escolhida: Otsu/componentes conexos para uma silhueta estimada por contraste, Canny para bordas, fundo local por convolução normalizada dentro da máscara para regiões escuras, PCA para orientação/alongamento, fecho convexo e defeitos de convexidade, reflexão nos dois eixos PCA para simetria aproximada, Hough para segmentos e contornos para estruturas curvas. Nenhum modelo de IA é usado.

Uma candidata a abertura exige componente escuro alongado, contraste com seu anel interno à marcação, dois lados com ajustes aproximadamente paralelos e término afastado do limite da seleção. As medidas incluem extensão projetada (não comprimento percorrido de uma fissura curva), espessura média, orientação, intensidade, contraste, erro dos ajustes e suporte do entorno. Esse suporte descreve continuidade local de pixels, não uma conexão física comprovada. Não se infere profundidade de cavidades nem se reconhecem objetos. A silhueta por contraste pode falhar com iluminação ou texturas complexas; nesse caso o resumo informa que área, orientação e simetria descrevem o limite marcado, sem apresentá-lo como um contorno descoberto.

Teste específico: `python -m unittest test_morphological_region -v`.

## Forensic Texture Analysis

Abra uma imagem e use **Análise → Forensic Texture Analysis**, também disponível na barra **Análise**. A ferramenta abre um painel à direita e usa o visualizador principal. A medição usa uma cópia do original limpo (após orientação EXIF), enquanto as camadas aparecem sobre a imagem com os ajustes atuais. Zoom, navegação, rotação, comparação com original e desenho continuam disponíveis; desenhos ficam acima das camadas. Use **Navegar** e clique sem arrastar para inspecionar uma região. Os cliques são convertidos da imagem rotacionada para as coordenadas da imagem base.

Os controles, resumo, detalhes técnicos, dez regiões e exportações ficam no painel com rolagem vertical. Fechar o painel oculta as camadas e cancela uma análise em andamento, sem alterar filtros, desenhos ou histórico. Trocar de imagem limpa os resultados e cancela o processamento anterior; clique em **Analisar** para a nova foto. Resultados atrasados não são aplicados à imagem nova. Ajustar filtros não recalcula as métricas. As camadas são apenas de exibição: a cópia/exportação normal da imagem permanece sem elas; as exportações específicas do painel mantêm os mapas e sobreposições sobre o original. Não há escrita no original, IA generativa, super-resolution ou deconvolução.

Selecione **32×32, 64×64 e/ou 128×128** e clique em **Analisar**. O processamento é offline, em segundo plano, com cancelamento. Janelas têm passo de metade do tamanho, incluem as últimas linhas/colunas e são recortadas quando a imagem é menor que a janela. As coordenadas são do original orientado por EXIF, com origem `(0, 0)` no canto superior esquerdo; rotações manuais do visualizador não são aplicadas à análise.

- **Aplicar heatmap** liga/desliga a sobreposição; **Opacidade** ajusta a transparência. A roda dá zoom e arrastar move a imagem.
- O seletor mostra o **Texture Anomaly Score** ou a anomalia individual de high frequency, fine/coarse, gradiente, FFT, compression grid, RGB e boundary. É possível comparar a fusão multiescala com cada escala separadamente. Cores usam sempre o intervalo 0–1.
- **Incluir no score** permite ativar/desativar cada métrica sem repetir a análise. Todas começam com o mesmo peso; desativar todas zera o score. A API também aceita pesos numéricos não negativos.
- A lista mostra as dez janelas com maior score, suprimindo sobreposições superiores a 25% da menor janela; imagens pequenas podem ter menos de dez. Clicar na lista destaca a janela. Clicar no heatmap inspeciona a janela de maior score que cobre aquele pixel na escala escolhida. O valor agregado do pixel é mostrado separadamente do score da janela.
- **Exportar CSV** salva todas as janelas, coordenadas, medidas brutas, componentes FFT, fases módulo 8, correlações e scores individuais/final.
- Os três botões de imagem salvam PNG do mapa selecionado, original com esse mapa na opacidade atual, ou original marcado com as regiões. **Salvar todos os mapas** salva PNGs e arrays numéricos NPZ das anomalias individuais e score final, inclusive por escala, além de CSV e metadados JSON. Salva também mapas de medidas brutas por escala em `raw_metrics_*.npz` e prévias `raw_*.png`; os intervalos dessas prévias estão no JSON, pois as medidas possuem unidades diferentes. Cada exportação cria uma subpasta nova para proteger arquivos existentes.

### Medições e interpretação

O destaque padrão é **Limite manual**. O usuário define o corte: valores abaixo dele ficam transparentes; no corte já aparece amarelo visível, com a opacidade escolhida. A cor escurece progressivamente até vermelho escuro em **100%**, sem usar o máximo da imagem para reajustar a escala. Por exemplo, corte em 50% distribui as cores entre 50% e 100%; corte em 10% distribui entre 10% e 100%. O limite é inclusivo. Com corte em 100%, apenas valores de 100% aparecem, em vermelho escuro. Esse controle usa os valores do mapa selecionado, mantendo os cálculos originais.

**Mais fortes nesta imagem (5%)** continua disponível como alternativa: mostra em vermelho os pixels a partir do percentil 95 do mapa selecionado, incluindo empates, e escurece o restante. Um contorno branco separa as áreas destacadas. A cruz branca localiza o maior valor; **Ir ao maior valor** centraliza esse ponto e abre seu resumo. Esse contraste é relativo à imagem e pode destacar scores baixos; o valor real continua visível. Mapas uniformes não recebem destaque nesse modo.

Os quadrados agora ficam desligados por padrão. **Mostrar janelas de medição** permite recuperá-los: são limites das janelas de cálculo, não contornos exatos de uma anomalia. O mapa também pode ter transições retangulares porque agrega essas janelas; o destaque não inventa um contorno de objeto. Picos nas bordas são identificados na interface, pois ali há menos vizinhança disponível para comparação. Isso não altera nem exclui os scores das bordas.

**Destacar áreas mais anômalas** adiciona uma camada opcional de amarelo a vermelho sobre as áreas que atingem a **Intensidade mínima** escolhida (inicialmente 40%). O vermelho indica valores mais altos da métrica/escala selecionada; áreas abaixo do limite ficam transparentes. A camada possui opacidade própria, informa a porcentagem da área destacada e pode ser salva com **Salvar original + destaques**. Para vê-la sozinha sobre a imagem original, desative **Aplicar heatmap**. Se nenhuma área atingir o limite, a interface informa isso; reduzir o limite revela diferenças menores, sem alterar os scores ou a imagem original.

A janela apresenta primeiro **Resumo da análise**, com nomes amigáveis, intensidade em porcentagem e categorias: Muito baixa `[0; 0,20)`, Baixa `[0,20; 0,40)`, Moderada `[0,40; 0,60)`, Alta `[0,60; 0,80)` e Muito alta `[0,80; 1]`. Esses rótulos descrevem os valores existentes; não mudam o detector. **Detalhes técnicos**, recolhido por padrão, preserva os nomes e números originais.

Cada métrica mostra a porcentagem das **outras janelas da imagem**, em todas as escalas analisadas, que têm valor estritamente menor. Empates não contam como inferiores; se houver apenas uma janela, a comparação fica indisponível. As janelas se sobrepõem, portanto essa comparação não representa porcentagem da área da imagem. A interpretação curta considera as métricas ativas, sua intensidade e posição relativa; uma diferença pequena pode estar entre as maiores de uma imagem uniforme. Correlação RGB sem variância suficiente é identificada como não interpretável. Categorias e percentis são apenas apresentação, implementada em `forensic_texture_presentation.py`; os cálculos e arquivos exportados permanecem iguais.

O resumo distingue **Ponto clicado**, **Região analisada**, **Tamanho da região**, **Valor visual do heatmap** (métrica e escala exibidas) e **Score real da região** (janela selecionada). Isso permite reconhecer rapidamente uma região comum ou incomum dentro daquela imagem, antes de abrir os detalhes.

`forensic_texture_analyzer.py` contém `ForensicTextureAnalyzer`, independente de Qt. `forensic_texture_ui.py` contém os controles, execução em thread e visualização. `METRICS` centraliza os componentes usados pelos seletores e pela combinação, enquanto menu e barra Análise acomodam novas ferramentas.

A entrada é RGB/grayscale `uint8` (RGBA tem o alfa ignorado). O grayscale usa OpenCV; resíduo = imagem − Gaussian sigma 1; RMS é medido em níveis de cinza de 8 bits. Fine/coarse divide a energia desse resíduo pela energia de Gaussian sigma 2 − Gaussian sigma 4, com piso 0,0625 no denominador. O gradiente é a média da magnitude Sobel 3×3. A FFT remove a média, aplica Hann e mede quatro bandas radiais, quatro setores angulares e concentração no pico. Compression grid compara diferenças adjacentes nas oito fases de X e Y usando coordenadas globais. RGB mede Pearson R/G, R/B, G/B; canais sem variância produzem correlação zero e `rgb_valid=False` (não interpretável como descorrelação). Boundary compara RMS do resíduo e gradiente com um anel externo de largura de 1/4 da janela, limitado às bordas da imagem.

As três medidas escalares de energia/detalhe/gradiente usam `log1p` antes da normalização. Para cada componente, desvios robustos de mediana/MAD são comparados com a imagem inteira (peso 0,2), janelas de luminosidade semelhante (0,3) e vizinhos imediatos (0,5). Pisos de dispersão evitam divisão por zero; `1 − exp(−z/3)` leva os desvios a 0–1. Janelas sobrepostas são promediadas por pixel; a fusão usa metade da média entre escalas e metade do máximo, preservando respostas pequenas. O score final é a média ponderada dos mapas de anomalia.

**O score é uma medida relativa, não uma probabilidade de manipulação.** Texturas naturais, iluminação, distância, foco e processamento da câmera podem gerar diferenças. A comparação contextual reduz esse efeito, mas não identifica materiais nem elimina falsos positivos. A periodicidade módulo 8 é uma assinatura de pixels, não uma inspeção dos coeficientes JPEG; redimensionamento e orientação podem mudar sua fase. Grandes imagens exigem mais tempo e memória, pois não são reduzidas antes da medição.

Dependências adicionais: NumPy e OpenCV (`opencv-python-headless`, sem outra interface gráfica). Instale com o ambiente virtual do projeto: `python -m pip install -r requirements.txt`. Depois de instaladas, a análise não acessa a rede. Testes específicos: `python -m unittest test_forensic_texture -v`.

Aplicativo desktop em Python para visualizar, ajustar e marcar imagens de planetas e luas, sem modificar os originais.

## Configurar planetas, missões e pastas

Abra **Missões → Configurar planetas e missões...** (também disponível na barra de ferramentas).

1. Escolha a **pasta-base das coleções**.
2. Selecione o planeta e a missão na árvore. Há busca por nome e um catálogo inicial extensível, incluindo acervos históricos; a presença no catálogo não indica que a missão continua em operação.
3. Confira a pasta efetiva: `pasta-base/planeta/missions/missão`. Os SOLs, datas, órbitas ou diretórios do acervo ficam dentro dela.
4. Para preservar uma coleção já existente, marque **Usar uma pasta existente ou personalizada** e aponte para a pasta que contém os SOLs ou imagens daquela missão.
5. Nas missões com download integrado, configure a atualização automática e o SOL inicial usado pelo botão de reverificação.
6. Clique em **Salvar**, ou **Salvar e abrir missão** para começar a visualizar a coleção escolhida.

O menu **Missões** separa as coleções por planeta e missão. Cada missão mantém pasta, imagem selecionada e informações de download próprias, mesmo que use o mesmo leitor de imagens locais. As pastas padrão são criadas ao abrir a missão. Alterar o caminho não move arquivos existentes.

Use **Adicionar missão...** para cadastrar qualquer missão ou corpo celeste que não esteja no catálogo. Cadastros personalizados aceitam nome, planeta, organização de pastas, caminho e endereço do acervo. Ocultar ou remover um cadastro não apaga imagens.

**Disponibilidade de downloads:** Curiosity, Perseverance, MRO/HiRISE, Mars Express/HRSC, LRO/LROC NAC e Kaguya/HDTV têm conectores integrados. As outras missões usam imagens locais e seus portais oficiais; cadastrar uma missão não cria automaticamente seu conector. Imagens locais podem estar na pasta da missão ou em subpastas, inclusive datas em vários níveis. São aceitos JPEG, PNG, TIFF, BMP e WebP; arquivos científicos como IMG/FITS exigem conversão prévia.

A coleção anterior do Curiosity é migrada como pasta personalizada, mantendo o caminho e as anotações. Configure uma nova pasta padrão quando desejar; a movimentação do acervo existente é separada da configuração.

O projeto pode ficar separado das coleções. Exemplo:

```text
pesquisas/
├── planetary_image_studio/
│   ├── main.py
│   ├── app.py
│   └── sources/
├── marte/
│   └── missions/
│       ├── curiosity/
│       │   ├── SOL2795/
│       │   └── SOL2796/
│       └── perseverance/
└── lua/
    └── missions/
        └── lunar reconnaissance orbiter/
```

O programa também aceita outra pasta pela linha de comando:

```bash
python main.py --mission curiosity /caminho/para/marte/missions/curiosity
python main.py --mission perseverance /caminho/para/marte/missions/perseverance
python main.py --source local /caminho/para/Lua/MinhaMissao
```

## Instalação

Recomendo usar um ambiente virtual:

### Linux

```bash
cd /caminho/para/planetary_image_studio
bash instalar_linux.sh
bash executar_linux.sh
```

### Windows

```bat
cd C:\caminho\para\planetary_image_studio
instalar_windows.bat
executar_windows.bat
```

Sem argumentos, o programa retoma a última sessão. Os scripts usam diretamente o Python da pasta `.venv`, sem depender de caminhos de ativação que mudam ao renomear o projeto.

## Recursos

- **Auto Zoom**, na barra e no menu **Visualizar**, mantém o nível de ampliação e a posição da área visualizada ao navegar, facilitando a comparação de imagens parecidas. Se a próxima imagem for menor, a posição fica limitada à área disponível. Desativado, cada imagem volta a se ajustar à janela. A opção é lembrada ao reabrir; a primeira imagem da sessão se ajusta à janela.

- Atalhos: **E** equilibra cores, **O** seleciona Oval, **L** seleciona Lápis e **T** seleciona Texto. **Ctrl+Seta direita/esquerda** gira 90° na direção correspondente.
- **N** ou **Seta direita**: próxima imagem. **B** ou **Seta esquerda**: imagem anterior.
- As setas dos controles de ajuste avançam de **2 em 2** (ou **0,02** nos controles decimais, como contraste, cor e meios-tons).
- Os botões das barras têm ícones. Em **Visualizar → Mostrar texto nos botões das barras**, desmarque para exibir somente ícones, com dicas ao passar o mouse. A preferência é salva; os nomes dos controles numéricos continuam visíveis para identificar cada ajuste.

- Lista de coleções à esquerda; na missão Curiosity, os diretórios `SOLxxxx` aparecem com o Sol mais recente primeiro.
- Thumbnails horizontais na parte inferior.
- Primeira imagem da coleção é aberta automaticamente.
- Clique numa thumbnail para trocar a imagem principal.
- **Roda do mouse sobre a imagem:** zoom, sem precisar de Ctrl.
- O zoom usa interpolação suave apenas na exibição, para reduzir o aspecto quadriculado dos pixels. Mantém as proporções e não altera os pixels da imagem, as anotações ou a exportação. É independente do ajuste **Suavizar imagem**; não recupera detalhes ausentes no original.
- **Botão esquerdo + arrastar:** pan.
- **Botão direito na imagem:**
  - `Copy`: copia a imagem atualmente exibida para o clipboard.
  - `Open`: abre o arquivo original no GIMP.
  - `About`: consulta metadados da imagem no site/API da NASA.
- Menu e toolbar:
  - ajuste à janela;
  - tamanho real 1:1;
  - contraste +/-;
  - saturação/cor +/-;
  - rotação esquerda/direita;
  - reset dos ajustes.
- Setas esquerda/direita: imagem anterior/próxima.
- `F5`: atualiza a lista de coleções.

## Desenhos e ajustes por imagem

**Equilibrar cores**, na barra de ferramentas e no menu **Imagem**, aplica uma correção automática moderada para reduzir dominantes como o amarelo. Clique novamente para desativar. É uma estimativa baseada nas cores médias da foto, não uma calibração de cores reais; cenas naturalmente coloridas também podem ser neutralizadas. Altera apenas as cores da versão editada, sem mudar formas ou o arquivo original. O ajuste é salvo por imagem, participa de Desfazer/Refazer, Comparar original e Resetar ajustes, e aparece na cópia/exportação editada.

A barra **Desenho** permite marcar a imagem sem alterar o arquivo original:

O menu **Desenho** oferece as mesmas ferramentas e configurações, além de mostrar ou ocultar a barra. Ao trocar de imagem, a ferramenta volta automaticamente para **Hand (Navegar)**.

### Selecionar e editar marcações

Com **Hand (Navegar)** ou **Selecionar elemento**, clique em um círculo, texto ou traço existente para mostrar suas alças. Arraste o elemento para movê-lo e arraste uma alça de canto para redimensioná-lo. Círculos mantêm a forma circular; textos mudam o tamanho da fonte. Na ferramenta Hand, arrastar uma região sem marcações continua movendo a imagem.

Use **Editar texto...** ou dê dois cliques sobre um texto para modificar seu conteúdo. **Excluir elemento (Delete)** remove a marcação selecionada. Mover, redimensionar, editar e excluir são salvos automaticamente e podem ser desfeitos ou refeitos. As alças são apenas controles da interface e não aparecem na imagem copiada ou exportada.

### Inverter cores e exportar uma área

**Inverter cores**, na barra de imagem e no menu **Imagem**, aplica um negativo à imagem, preservando a transparência e as cores escolhidas para as marcações. Esse ajuste é salvo junto das anotações, pode ser desfeito e é removido por **Resetar ajustes**.

Na barra **Seleção e recorte**, escolha **Selecionar área** e arraste um retângulo. **Copiar área** envia o recorte ao clipboard; **Exportar área PNG...** permite escolher onde salvá-lo. O recorte contém os desenhos, textos e ajustes visíveis, na resolução da imagem, sem as bordas de seleção. **Limpar seleção** remove o retângulo. Trocar de imagem, ferramenta ou girar a imagem também limpa a seleção da área.

### Ferramentas de desenho

- **Hand (Navegar):** arraste com o botão esquerdo para mover a imagem. A **roda do mouse sobre a imagem** controla o zoom em qualquer ferramenta, sem precisar de Ctrl.
- **Lápis:** arraste para desenhar livremente; um clique marca um ponto.
- **Oval:** arraste de um canto ao canto oposto para definir a largura e a altura.
- **Retângulo:** arraste de um canto ao canto oposto para marcar uma área retangular.
- **Traço (px):** espessura do lápis e do contorno do círculo, inicialmente 3 pixels. A medida usa pixels da imagem, independentemente do zoom.
- **Cor:** define a cor dos próximos traços, círculos e textos. Cada marcação mantém sua própria cor e espessura.
- **Texto:** clique na imagem e digite o texto. **Texto (px)** controla o tamanho da fonte.
- **Desfazer (Ctrl+Z)** e **Refazer (Ctrl+Shift+Z):** recuperam até 50 etapas de desenhos e ajustes, inclusive depois de fechar e reabrir o programa.
- **Copiar imagem final (Ctrl+C):** copia a imagem na resolução resultante, incluindo desenhos, textos, contraste, saturação e rotação.

Ao terminar cada desenho, inserir texto ou alterar um ajuste, o programa salva automaticamente um arquivo ao lado da imagem: por exemplo, `foto.jpg.annotations.json`. Ele contém as marcações, os ajustes, a cor e os tamanhos atuais das ferramentas e o histórico. Ao selecionar a imagem original novamente, tudo é reaplicado. Mantenha esse arquivo junto da imagem ao mover ou copiar sua coleção.

**Resetar ajustes** restaura contraste, saturação e rotação; os desenhos permanecem. Essa operação também pode ser desfeita. O indicador **Salvo** confirma o salvamento; falhas são indicadas na barra e não substituem o último arquivo salvo.

## Observações sobre os arquivos originais

Os ajustes de contraste, cor e rotação são **não destrutivos**: alteram somente a visualização e a imagem copiada para o clipboard. O arquivo original não é modificado.

O comando `Open` procura automaticamente `gimp`, `gimp-3.0` ou `gimp-2.10` no PATH, e também tenta locais comuns no Windows/macOS.

Na missão Curiosity, o `About` requer conexão com a Internet. Primeiro o programa tenta localizar a imagem pelo `imageid` derivado do nome original do arquivo. Se isso não funcionar, pesquisa os registros do Sol selecionado e compara os nomes dos arquivos. Na fonte local, a consulta permanece offline.

## Sessões e compatibilidade

As configurações são salvas em `planetary_image_studio_state.json`, junto ao projeto, com alternativa em `.planetary_image_studio_state.json` na pasta pessoal quando necessário. Uma sessão antiga em `curiosity_viewer_state.json` ou `.curiosity_sol_viewer_state.json` é migrada automaticamente quando não existe sessão nova válida. O arquivo antigo permanece como backup.

As pastas `SOLxxxx`, os arquivos originais e os acompanhamentos `*.annotations.json` continuam válidos. A mudança do nome do projeto não exige renomear as coleções ou as anotações.

## Estrutura para desenvolvimento

```text
main.py                       # Entrada do aplicativo
app.py                        # Interface e visualizacao
config.py                     # Identidade, sessao e migracao
missions.py                   # Perfis e caminhos por planeta e missao
mission_settings.py           # Tela de configuracao
mission_catalog.py            # Catalogo inicial de missoes
catalog.py                    # Descoberta de imagens
image_annotations.py          # Desenhos, ajustes e salvamento
annotation_editing.py         # Selecao, handles e exportacao
sources/
    base.py                   # Contrato para fontes de imagens
    curiosity.py              # SOLs, metadados e download Curiosity
    perseverance.py           # Feed de imagens completas por SOL
    archives.py               # HiRISE, LROC, ESA HRSC e Kaguya
    local.py                  # Colecoes locais de Lua e outros
    __init__.py               # Registro das fontes disponiveis
```

Para adicionar uma missão, implemente `ImageSource` e registre a fonte em `sources/__init__.py`. A interface consulta as coleções e capacidades dessa fonte; as ferramentas de imagem e anotações são compartilhadas. Atribua o backend validado à entrada correspondente em `mission_catalog.py`.

Execute os testes offline com:

```bash
python -m unittest discover -v
```

O `.gitignore` exclui o ambiente virtual, caches, sessões pessoais e anotações de pesquisa do futuro repositório.

## Referências dos portais do catálogo

- [NASA: imagens brutas das missões](https://science.nasa.gov/solar-system/moon/where-to-find-mission-raw-images/).
- [NASA Planetary Data System: busca de acervos](https://pds.nasa.gov/datasearch/data-search/).
- [ESA Planetary Science Archive](https://archives.esac.esa.int/psa/).
- [JAXA DARTS: Akatsuki](https://darts.isas.jaxa.jp/en/missions/akatsuki) e [Kaguya](https://legacy.darts.isas.jaxa.jp/app/pdap/selene/).
- [ISRO Science Data Archive / PRADAN](https://pradan.issdc.gov.in/).

Os portais foram consultados em 07/09/2026. Alguns exigem cadastro, seleção de instrumentos ou conversão de formatos. O catálogo pode ser ampliado com novas missões sem alterar as ferramentas de desenho.


Configuração simplificada: escolha a pasta-base em Missões > Configurar planetas e missões.
O destino padrão é `pasta-base/planeta/missions/missão`, com nomes de pasta em minúsculas.
Selecione a missão na barra "Missão de trabalho"; a pasta correspondente é criada e aberta automaticamente.
Marque "Atualizar automaticamente ao abrir esta missão" para iniciar a atualização ao salvar e nas próximas aberturas.
Os downloads disponíveis e seus formatos estão descritos abaixo.
Pastas personalizadas e os demais ajustes ficam em "Mostrar opções avançadas" e têm prioridade sobre a pasta-base.


## Downloads de Marte e Lua (0.5.0)

| Missão no seletor | Agência / instrumento | Produto baixado |
| --- | --- | --- |
| Curiosity | NASA/JPL | Imagens do catálogo MSL por SOL (conector existente) |
| Perseverance | NASA/JPL | PNG/JPEG `full_res` do feed raw, por SOL; sem usar miniaturas |
| Mars Reconnaissance Orbiter | NASA / HiRISE | JPEGs browse do PDS, vermelho e versões em cores, por observação |
| Mars Express | ESA / HRSC | JPEGs no tamanho original da galeria oficial, filtrados pela descrição HRSC; perspectivas e mapas processados |
| Lunar Reconnaissance Orbiter | NASA / LROC NAC | TIFF CDR PTIF de múltipla resolução com compressão com perdas; exclui imagens de calibração |
| Kaguya - SELENE | JAXA/NHK / HDTV | JPEGs `browse/large` das sequências fotográficas, por observação; sem vídeos |

Os JPEGs HiRISE e Kaguya são produtos de visualização. O app não baixa nem converte os JP2/IMG/FITS científicos desses instrumentos. HRSC usa a galeria publicada, e não todo o acervo científico ESA. TIFFs LROC podem ser muito grandes: a amostra validada tem 2.532 × 52.224 pixels; a visualização depende dos limites de memória e decodificação do computador.

Selecione a missão de trabalho e habilite **Atualizar automaticamente ao abrir esta missão**. Cada missão usa sua pasta na base já configurada. Os novos downloads ficam desativados até você habilitá-los. Curiosity e Perseverance conferem primeiro o catálogo completo, do SOL 0 ao mais recente, com cache em disco por missão e por SOL. A atualização normal verifica também lacunas nas pastas locais; o botão de SOL inicial permite limitar os downloads a partir de um SOL escolhido.

Catálogos históricos são reutilizados por até 7 dias e os dos últimos 8 SOLs por até 5 minutos. Se a leitura for interrompida, os SOLs já consultados são aproveitados na retomada. No menu **Downloader > Limpar cache de catálogos e reler tudo**, você pode forçar uma nova consulta completa sem apagar imagens ou marcações.

Nas quatro fontes de acervo, cada atualização baixa até **10 observações**, com todos os arquivos selecionados dessas observações. **Baixar próximo lote** continua o catálogo de onde parou, inclusive após reabrir. **Reverificar início do catálogo** volta ao começo sem apagar imagens; use-o para conferir publicações recentes. Isso não é uma sincronização integral em segundo plano de todo o arquivo. LROC percorre fases recentes primeiro, mantendo a ordem de observações fornecida pelo catálogo; os demais começam pelas páginas ou meses mais recentes.

O cursor fica em `.archive-download.json` dentro da missão e avança somente após uma observação completa. Arquivos `.part` permitem retomada HTTP quando o servidor suporta Range. Falhas de catálogo, rede ou imagem inválida são mostradas no painel e preservam a posição. Cada arquivo de acervo ganha um `*.source.json` com o endereço de origem e dimensões; ele é separado das anotações.

Chandrayaan-2 continua com acesso externo porque o acervo exige cadastro/login. Chang'e e demais entradas sem conector validado permanecem identificadas como locais/externas.

Fontes usadas e verificadas em 07/09/2026:

- [Perseverance: imagens raw](https://mars.nasa.gov/mars2020/multimedia/raw-images/)
- [HiRISE: catálogo](https://www.uahirise.org/catalog/)
- [LROC: catálogo NAC](https://data.lroc.im-ldi.com/lroc/thumbnails)
- [ESA: galeria Mars Express](https://www.esa.int/ESA_Multimedia/Missions/Mars_Express/(result_type)/images)
- [JAXA: Kaguya HDTV](https://darts.isas.jaxa.jp/missions/kaguya/hdtv/index_en.html)
- [ISRO: acesso Chandrayaan](https://chmapbrowse.issdc.gov.in/)

Verificação: testes offline de parsing, retomada, cancelamento, falhas, integridade e preservação da seleção; downloads reais de amostras dos cinco novos conectores em pasta temporária. Nenhum download em massa foi iniciado nas coleções pessoais.


## Pausar, continuar e filtrar imagens

Durante um download, **Parar** interrompe após o bloco em andamento. Quando a tarefa encerra, o botão muda para **Continuar**, que retoma o mesmo SOL ou observação e aproveita arquivos parciais. A pausa fica salva por missão e é respeitada ao reabrir o app, mesmo com atualização automática habilitada. O menu de download acompanha o botão.

Acima das miniaturas, os filtros compactos podem ser combinados:

- **Coloridas**: detecta cores por amostragem dos pixels do arquivo original; uma imagem RGB cujos canais são iguais continua sendo considerada preto e branco. É uma classificação visual aproximada e não depende da cor de desenhos sobrepostos.
- **Editadas**: encontra marcações, textos, contraste, saturação, rotação e inversão presentes no estado atual ou no histórico salvo de anotações. Apenas escolher outra cor/espessura de lápis não conta como edição.
- **Pasta / Missão**: limita a busca à pasta/SOL atual ou pesquisa todos os SOLs/observações da missão em uso. Para encontrar todo o trabalho já marcado, selecione **Editadas** e **Missão**.

As opções **Coloridas**, **Editadas** e **Pasta / Missão** são salvas ao mudar e restauradas ao reabrir o aplicativo, reaplicando a busca mesmo quando a sessão anterior terminou sem resultados.

Ao trocar de SOL/pasta ou alterar os filtros, as miniaturas antigas são limpas imediatamente. A faixa inferior mostra **Carregando…**, uma barra animada e a contagem de arquivos verificados; depois mostra o progresso das miniaturas. As trocas de pasta após abrir o aplicativo são lidas em segundo plano, mesmo sem filtros. Uma busca vazia mostra uma mensagem explícita. Atualizações de downloads em segundo plano preservam a lista que está sendo usada.

A busca ocorre em segundo plano, mostra a quantidade verificada e preserva a imagem selecionada e o zoom quando ela atende aos filtros. Clicar em outra pasta na lateral volta ao escopo Pasta. Os filtros não alteram os originais nem restringem os downloads. Arquivos ilegíveis não entram nos resultados de classificação.


## Suavizar imagem

Use **Imagem → Suavizar imagem…** para reduzir ruído e granulação com intensidade de 0 a 100. A prévia mostra a região central em pixels originais; **Aplicar** processa a imagem inteira, e **Cancelar** não altera nada. O filtro usa mediana 3×3 combinada com o original conforme a intensidade, preservando dimensões e transparência.

O ajuste é aplicado antes dos desenhos e textos, salvo no `*.annotations.json` e incluído no desfazer/refazer, no filtro **Editadas** e na imagem final copiada ou exportada. **Resetar ajustes** remove a suavização. Arquivos de anotações anteriores usam intensidade zero. O arquivo original permanece intacto.


## Níveis, nitidez e comparação

No menu **Imagem**, **Níveis…** controla o ponto preto (0–254), o ponto branco (1–255) e os meios-tons/gamma (0,10–5,00). O ponto preto permanece abaixo do branco. **Nitidez…** aplica realce de bordas com intensidade de 0–300%; zero desativa. Ambos mostram prévia central em pixels originais, respeitando os outros ajustes. Aplicar cria uma etapa no histórico; cancelar não salva alterações.

Os ajustes são salvos por imagem, entram no filtro **Editadas**, são incluídos na cópia/exportação final e podem ser desfeitos/refeitos. **Resetar ajustes** restaura os valores neutros. Marcações e textos são desenhados depois desses filtros.

**Comparar original** (`Ctrl+Shift+O`) alterna entre a versão original sem ajustes/marcações e a versão editada, mantendo o zoom e a posição. A rotação atual é mantida para facilitar o alinhamento visual. A comparação não altera arquivos nem o histórico; copiar/exportar continua usando a imagem final editada. Ao trocar de imagem, escolher uma ferramenta ou aplicar um ajuste, a visualização volta à versão editada.


O botão direito sobre a imagem também oferece Níveis, Nitidez, Suavizar, contraste, cor, inversão, rotação, reset e comparação. **Comparar original** está na barra principal: pressionado mostra o original; desmarcado mostra a imagem modificada. O estado é compartilhado com o menu e o atalho.


Níveis, Nitidez e Suavização oferecem barras deslizantes maiores, valor numérico editável e atalhos de **10% a 100% do máximo do controle**, em passos de 10%. Por exemplo, Nitidez tem máximo 300: 10% seleciona 30. **Padrão** restaura o valor neutro. Nos Níveis, atalhos incompatíveis com os pontos preto/branco atuais ficam desativados. A prévia atualiza ao soltar a barra ou escolher um valor.


A faixa de miniaturas tem uma divisória horizontal acima dos filtros. Arraste para cima para ampliar as miniaturas ou para baixo para liberar espaço à imagem principal. As miniaturas acompanham a altura e continuam em uma única linha com rolagem horizontal. A altura escolhida é salva na sessão. O zoom manual da imagem é mantido; no modo Ajustar à janela, a imagem acompanha a área disponível.


**Botão central (rodinha) + arrastar:** move a imagem temporariamente com qualquer ferramenta selecionada. Ao soltar, a ferramenta permanece selecionada; o movimento não cria marcações. Girar a rodinha continua controlando o zoom. Se o botão central for pressionado durante um traço, o traço é concluído antes de iniciar o pan.


**Brilho…**, no menu Imagem, botão direito e barra principal, clareia ou escurece a imagem com prévia. O valor neutro é **100%**; abaixo escurece, acima clareia, até 200%. Os atalhos representam frações do máximo: 50% do máximo equivale ao valor neutro 100. **Padrão** volta diretamente a 100. O brilho fica salvo por imagem, entra em Editadas e suporta desfazer/refazer, reset, comparação e cópia/exportação final.
