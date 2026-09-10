# Planetary Image Studio

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

- **Auto Zoom**, na barra e no menu **Visualizar**, mantém o nível de ampliação da imagem anterior ao navegar e centraliza a próxima imagem. Desativado, cada imagem volta a se ajustar à janela. A opção é lembrada ao reabrir; a primeira imagem da sessão se ajusta à janela.

- Atalhos: **E** equilibra cores, **O** seleciona Oval, **L** seleciona Lápis e **T** seleciona Texto. **Ctrl+Seta direita/esquerda** gira 90° na direção correspondente.
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
