# Poquertini

Jogo de cartas de negociação: cada jogador tenta montar a melhor mão de poker trocando cartas com a mesa, com o banco e pelo mercado. A única mentira permitida é com o coringa.

Esta é a versão de terminal, com bots em três níveis de dificuldade, feita para testar as regras.

## Como rodar

Só precisa de Python 3.8 ou mais novo, sem dependências.

```bash
python poquertini.py                               # você + 3 bots (fácil, médio, difícil)
python poquertini.py --bots dificil,dificil,medio  # escolher os bots (2 a 7 jogadores)
python poquertini.py --assistir                    # só bots, com todas as mãos abertas
python poquertini.py --simular 300                 # estatística de vitórias, sem tela
```

Opções:

| Opção | O que faz |
|---|---|
| `--mao-rodadas N` | Voltas jogadas depois de alguém pedir Mão (padrão: 3) |
| `--congelar` | Quem pede Mão não joga nem troca até a revelação |
| `--pedido total` | Proibido pedir um naipe ou número que você tem |
| `--pedido leve` | Proibido pedir um número do qual você já tem 2 ou mais |
| `--delay S` | Segundos entre as jogadas dos bots (padrão: 1.2) |
| `--rodadas N` | Limite de rodadas antes da revelação forçada (padrão: 30) |
| `--seed N` | Semente para repetir partidas |
| `--sem-cor` | Desliga as cores |

Dentro do jogo, aperte `h` na sua vez para ver as regras.

## Regras

**Objetivo.** Terminar com a melhor mão de poker de 5 cartas, escolhidas entre as que você tem.

**Cartas.** Baralho de 52 cartas mais 2 coringas. Cada jogador começa com 6 cartas. O coringa não vale nada na revelação.

**Sua vez.** Você faz uma ação:

- **Troca na hora:** anuncia à mesa o que oferece e o que quer, cada um sendo um naipe ou um número, nunca os dois. Os outros respondem em ordem; o primeiro que aceitar faz a troca. Se ninguém aceitar, a ação é gasta.
- **Troca com o banco:** joga uma carta no cemitério, virada para cima, e compra uma do banco.
- **Aceitar oferta do mercado:** entrega uma carta que atende ao pedido e leva a carta exposta.
- **Pedir Mão:** o jogo segue por mais algumas voltas e então todos revelam.

Sem gastar ação:

- **Colocar no mercado:** deixa uma carta à vista com o que você quer por ela. Ela continua sendo sua até alguém aceitar.
- **Anunciar retirada:** a carta sai do mercado no início da sua próxima vez.

**Mentira.** Toda troca precisa ser cumprida de verdade, exceto com o coringa: quem tem um pode entregá-lo no lugar da carta prometida. Quem recebe joga o coringa no cemitério e compra uma carta do banco.

**Cemitério.** Só a carta do topo fica visível. Se o banco acabar, o cemitério (menos o topo) é embaralhado e vira o novo banco.

## Bots

- **Fácil:** joga meio no aleatório, mas não descarta cartas da sua melhor mão.
- **Médio:** calcula o valor esperado de cada ação com base no que está visível agora.
- **Difícil:** lembra todas as cartas que já viu, aprende com que frequência a mesa aceita trocas e sempre mente quando tem coringa.

Quando nenhuma ação melhora a mão, os bots médio e difícil fazem uma troca na hora feita para ser recusada (por exemplo, pedir um 2 tendo um par de 2), já que não é possível passar a vez.
