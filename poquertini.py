#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POQUERTINI — versão de terminal com bots

  python poquertini.py                                  # você + 3 bots (fácil, médio, difícil)
  python poquertini.py --bots dificil,dificil,medio     # escolher os bots
  python poquertini.py --assistir                       # só bots, todas as mãos abertas
  python poquertini.py --simular 300                    # estatística rápida, sem tela

Regras extras: --congelar   --pedido total|leve
Opções: --mao-rodadas 2 (voltas depois de pedir Mão)  --delay 1.2  --rodadas 30  --seed 42  --sem-cor
"""
import os, sys, random, time, argparse, shutil
from itertools import combinations
from collections import Counter
from functools import lru_cache

# ───────────────────────────── cartas ─────────────────────────────
SUITS = ['♠', '♥', '♦', '♣']
SUIT_NAME = {'♠': 'espadas', '♥': 'copas', '♦': 'ouros', '♣': 'paus'}
RANK_NAME = {11: 'J', 12: 'Q', 13: 'K', 14: 'A'}
JOKERS = [(0, 'J1'), (0, 'J2')]
FULL_DECK = [(r, s) for s in SUITS for r in range(2, 15)] + JOKERS
ALL_ATTRS = [('rank', r) for r in range(2, 15)] + [('suit', s) for s in SUITS]
LEVEL_NAME = {'facil': 'fácil', 'medio': 'médio', 'dificil': 'difícil', 'humano': 'humano'}
CAT_NAME = ['Carta alta', 'Par', 'Dois pares', 'Trinca', 'Sequência', 'Flush',
            'Full house', 'Quadra', 'Straight flush']
USE_COLOR = True


def col(s, code):
    return f"\033[{code}m{s}\033[0m" if USE_COLOR else s


def is_joker(c):
    return c[0] == 0


def rank_str(r):
    return RANK_NAME.get(r, str(r))


def card_str(c):
    if is_joker(c):
        return col('JK', '95;1')
    s = f"{rank_str(c[0])}{c[1]}"
    return col(s, '91;1' if c[1] in '♥♦' else '1')


def sort_view(hand):
    return sorted(hand, key=lambda c: (-c[0], c[1]))


def hand_str(hand):
    return '  '.join(card_str(c) for c in sort_view(hand))


def attr_str(a):
    if a[0] == 'rank':
        return f"número {rank_str(a[1])}"
    return f"naipe {a[1]} ({SUIT_NAME[a[1]]})"


def matches(c, a):
    if is_joker(c):
        return False
    return c[0] == a[1] if a[0] == 'rank' else c[1] == a[1]


def parse_attr(s):
    s = s.strip().lower()
    suits = {'e': '♠', 'espadas': '♠', '♠': '♠', 'c': '♥', 'copas': '♥', '♥': '♥',
             'o': '♦', 'ouros': '♦', '♦': '♦', 'p': '♣', 'paus': '♣', '♣': '♣'}
    if s in suits:
        return ('suit', suits[s])
    special = {'j': 11, 'q': 12, 'k': 13, 'a': 14, '1': 14}
    if s in special:
        return ('rank', special[s])
    if s.isdigit() and 2 <= int(s) <= 10:
        return ('rank', int(s))
    return None


# ───────────────────────── avaliação de mãos ─────────────────────────
def eval5(cards):
    if not cards:
        return (0,)
    ranks = sorted((c[0] for c in cards), reverse=True)
    cnt = Counter(ranks)
    groups = sorted(cnt.items(), key=lambda x: (-x[1], -x[0]))
    g = [x[0] for x in groups]
    flush = len(cards) == 5 and len({c[1] for c in cards}) == 1
    st = 0
    if len(cards) == 5 and len(cnt) == 5:
        if ranks[0] - ranks[4] == 4:
            st = ranks[0]
        elif ranks == [14, 5, 4, 3, 2]:
            st = 5
    if st and flush:
        return (8, st)
    if groups[0][1] == 4:
        return (7, *g)
    if groups[0][1] == 3 and len(groups) > 1 and groups[1][1] >= 2:
        return (6, *g)
    if flush:
        return (5, *ranks)
    if st:
        return (4, st)
    if groups[0][1] == 3:
        return (3, *g)
    if groups[0][1] == 2 and len(groups) > 1 and groups[1][1] == 2:
        return (2, *g)
    if groups[0][1] == 2:
        return (1, *g)
    return (0, *ranks)


@lru_cache(maxsize=400000)
def _best(key):
    real = [c for c in key if not is_joker(c)]   # coringa não vale nada na revelação
    if len(real) <= 5:
        return eval5(real), tuple(real)
    return max(((eval5(list(cb)), cb) for cb in combinations(real, 5)), key=lambda t: t[0])


def best_hand(hand):
    return _best(tuple(sorted(hand)))


@lru_cache(maxsize=400000)
def _score(key):
    t = _best(key)[0]
    s, f = float(t[0]), 1.0
    for v in t[1:]:
        f /= 15.0
        s += v * f
    return s


def score(hand):
    return _score(tuple(sorted(hand)))


# ───────────────────────────── estado ─────────────────────────────
class Quit(Exception):
    pass


class Player:
    def __init__(self, name, level):
        self.name, self.level = name, level
        self.is_bot = level != 'humano'
        self.hand = []
        self.memory = set()      # cartas cuja posição o bot difícil lembra
        self.stats = {}          # nome do oponente -> [aceites, propostas]


class Listing:
    def __init__(self, owner, card, want):
        self.owner, self.card, self.want = owner, card, want
        self.removing = False


class Game:
    def __init__(self, levels, human=True, show=True, reveal=False, delay=1.2,
                 max_rounds=30, rng=None, mao_rounds=1, freeze=False, own_want='off'):
        self.rng = rng or random.Random()
        self.freeze = freeze          # ideia 1: quem pede Mão fica congelado até a revelação
        self.own_want = own_want      # ideia 3: 'off' | 'total' (nada que você tem) | 'leve' (número de que já tem 2+)
        self.mao_rounds, self.calls_left = mao_rounds, 0
        self.show, self.reveal_all, self.delay, self.max_rounds = show, reveal, delay, max_rounds
        self.players = []
        if human:
            self.players.append(Player('Você', 'humano'))
        for i, lv in enumerate(levels):
            self.players.append(Player(f"Bot{i + 1}", lv))
        self.human = self.players[0] if human else None
        self.deck = FULL_DECK[:]
        self.rng.shuffle(self.deck)
        self.grave, self.market, self.logs = [], [], []
        self.round = 1
        self.turn = self.start = self.rng.randrange(len(self.players))
        self.caller = None
        self.flash = ''
        for _ in range(6):
            for p in self.players:
                p.hand.append(self.deck.pop())
        self.log(f"Cartas distribuídas. {self.players[self.turn].name} começa.")

    # ── utilidades ──
    def log(self, msg, only=None):
        self.logs.append((msg, only))

    def frozen(self, p):
        return self.freeze and self.caller is not None and self.players[self.caller] is p

    def allowed_wants(self, p):
        if self.own_want == 'total':
            return [w for w in ALL_ATTRS if not any(matches(c, w) for c in p.hand)]
        if self.own_want == 'leve':
            return [w for w in ALL_ATTRS
                    if not (w[0] == 'rank' and sum(matches(c, w) for c in p.hand) >= 2)]
        return ALL_ATTRS

    def want_ok(self, p, w):
        return w in self.allowed_wants(p)

    def free(self, p):
        listed = {l.card for l in self.market if l.owner is p}
        return [c for c in p.hand if c not in listed]

    def give_cands(self, p, attr):
        return [c for c in self.free(p) if matches(c, attr) or is_joker(c)]

    def seen_by_all(self, card):
        for p in self.players:
            p.memory.add(card)

    def draw(self, p):
        if not self.deck and len(self.grave) > 1:
            cards = self.grave[:-1]
            self.grave = self.grave[-1:]
            self.deck = cards
            self.rng.shuffle(self.deck)
            for pl in self.players:
                pl.memory -= set(cards)
            self.log(col("O banco acabou: o cemitério (menos o topo) foi embaralhado e virou banco.", '33'))
        if self.deck:
            c = self.deck.pop()
            p.hand.append(c)
            return c
        return None

    def handle_joker(self, receiver, card):
        if is_joker(card):
            receiver.hand.remove(card)
            self.grave.append(card)
            self.seen_by_all(card)
            new = self.draw(receiver)
            self.log(col(f"🃏 {receiver.name} recebeu um CORINGA — era mentira! Descartou e comprou do banco.", '95'))
            if new:
                self.log(f"   {receiver.name} comprou {card_str(new)}.", only=receiver)

    # ── ações ──
    def do_bank(self, p, card):
        p.hand.remove(card)
        self.grave.append(card)
        self.seen_by_all(card)
        new = self.draw(p)
        self.log(f"{p.name} trocou com o banco: jogou {card_str(card)} no cemitério.")
        if new:
            self.log(f"   {p.name} comprou {card_str(new)}.", only=p)
        if is_joker(new or (1, '')):
            pass  # puxar coringa do banco não é mentira: fica na mão (vale nada na revelação)

    def do_trade(self, p, offer, want, give):
        """Oferta para a mesa toda: os outros respondem em ordem; o primeiro que aceitar fica com a troca."""
        self.log(f"{p.name} → mesa: oferece {attr_str(offer)}, quer {attr_str(want)}.")
        n = len(self.players)
        i0 = self.players.index(p)
        t = resp = None
        for k in range(1, n):
            cand = self.players[(i0 + k) % n]
            if self.frozen(cand):
                continue
            r = self.human_respond(cand, p, offer, want) if not cand.is_bot else bot_respond(self, cand, p, offer, want)
            for obs in self.players:                # aceitar/recusar é público
                st = obs.stats.setdefault(cand.name, [0, 0])
                st[1] += 1
                st[0] += r is not None
            if r is None:
                self.log(f"   {cand.name} recusou.")
            else:
                t, resp = cand, r
                break
        if t is None:
            self.log("   Ninguém aceitou.")
            return
        if give is None:
            cands = self.give_cands(p, offer)
            give = cands[0]
            if len(cands) > 1:
                i = self.choose(f"{t.name} aceitou! Qual carta você entrega?",
                                [card_str(c) + (' (mentira!)' if is_joker(c) else '') for c in cands])
                give = cands[i or 0]
        p.hand.remove(give); t.hand.remove(resp)
        p.hand.append(resp); t.hand.append(give)
        p.memory.add(give); t.memory.add(resp)
        self.log(f"   {t.name} aceitou. Troca feita.")
        self.log(f"   {p.name} deu {card_str(give)} e recebeu {card_str(resp)}.", only=p)
        self.log(f"   {t.name} deu {card_str(resp)} e recebeu {card_str(give)}.", only=t)
        self.handle_joker(t, give)
        self.handle_joker(p, resp)

    def do_place(self, p, card, want):
        self.market.append(Listing(p, card, want))
        self.seen_by_all(card)
        self.log(f"{p.name} pôs {card_str(card)} no mercado, querendo {attr_str(want)}.")

    def do_accept(self, p, l, give):
        o = l.owner
        self.market.remove(l)
        p.hand.remove(give); o.hand.remove(l.card)
        p.hand.append(l.card); o.hand.append(give)
        p.memory.add(give)
        self.log(f"{p.name} aceitou a oferta de {o.name}: levou {card_str(l.card)} entregando {attr_str(l.want)}.")
        self.log(f"   {p.name} entregou {card_str(give)}.", only=p)
        self.log(f"   {o.name} recebeu {card_str(give)}.", only=o)
        self.handle_joker(o, give)

    def do_call(self, p):
        self.caller = self.players.index(p)
        self.calls_left = self.mao_rounds
        voltas = 'Mais uma volta' if self.mao_rounds == 1 else f"Mais {self.mao_rounds} voltas"
        self.log(col(f"⚑ {p.name} pediu MÃO! {voltas} e todos revelam.", '93;1'))

    def announce_removal(self, p, l):
        l.removing = True
        self.log(f"{p.name} anunciou que vai retirar {card_str(l.card)} do mercado.")

    def execute(self, p, act):
        k = act[0]
        if k == 'bank':
            self.do_bank(p, act[1])
        elif k == 'trade':
            self.do_trade(p, *act[1:])
        elif k == 'place':
            self.do_place(p, act[1], act[2])
        elif k == 'accept':
            self.do_accept(p, act[1], act[2])
        elif k == 'call':
            self.do_call(p)
        else:
            self.log(f"{p.name} passou a vez.")

    # ── laço principal ──
    def play(self):
        n = len(self.players)
        while True:
            p = self.players[self.turn]
            if self.frozen(p):
                self.log(col(f"{p.name} está congelado (pediu Mão) e não joga.", '90'))
                self.turn = (self.turn + 1) % n
                if self.turn == self.start:
                    self.round += 1
                if self.turn == self.caller:
                    self.calls_left -= 1
                    if self.calls_left <= 0:
                        return self.showdown()
                if self.show:
                    self.render(); time.sleep(self.delay)
                continue
            for l in [l for l in self.market if l.owner is p and l.removing]:
                self.market.remove(l)
                self.log(f"{p.name} retirou {card_str(l.card)} do mercado.")
            if p.is_bot:
                self.execute(p, choose_action(self, p))
                if self.show:
                    self.render()
                    time.sleep(self.delay)
            else:
                self.human_turn(p)
            self.turn = (self.turn + 1) % n
            if self.turn == self.start:
                self.round += 1
                if self.round <= self.max_rounds:
                    self.log(col(f"── Rodada {self.round} ──", '90'))
            if self.caller is not None and self.turn == self.caller:
                self.calls_left -= 1
                if self.calls_left <= 0:
                    return self.showdown()
                self.log(col(f"⚑ Falta{'m' if self.calls_left > 1 else ''} {self.calls_left} volta(s) para a revelação.", '93'))
            if self.round > self.max_rounds:
                self.log(col("Limite de rodadas atingido — revelação forçada.", '33'))
                return self.showdown()

    def showdown(self):
        res = [(best_hand(p.hand), p) for p in self.players]
        top = max(r[0][0] for r in res)
        winners = [p for (t, _), p in res if t == top]
        if self.show:
            self.reveal_all = True
            lines = [col(' REVELAÇÃO', '1;93')]
            for (t, cards), p in sorted(res, key=lambda r: r[0][0], reverse=True):
                rest = [c for c in p.hand if c not in cards]
                trophy = col('  🏆', '93') if p in winners else ''
                lines.append(f"  {p.name:<6} {CAT_NAME[t[0]]:<15} {hand_str(cards)}"
                             + (col('  | ' + ' '.join(card_str(c) for c in rest), '2') if rest else '') + trophy)
            lines.append(col(f"  Vencedor: {', '.join(w.name for w in winners)}", '1;92') + "   [Enter]")
            self.ask('\n'.join(lines))
        return winners

    # ── tela ──
    def render(self, prompt=''):
        if not self.show:
            return
        cols, rows = shutil.get_terminal_size((100, 32))
        L = [col(f" POQUERTINI — Rodada {min(self.round, self.max_rounds)}/{self.max_rounds} ".center(cols, '═'), '1;36')]
        status = (f" Banco: {len(self.deck)}   Cemitério: "
                  f"{card_str(self.grave[-1]) if self.grave else '—'} (topo de {len(self.grave)})")
        if self.caller is not None:
            status += col(f"   ⚑ {self.players[self.caller].name} pediu MÃO! (faltam {self.calls_left} volta(s))", '93;1')
        L += [status, '', col(' JOGADORES', '1')]
        for i, p in enumerate(self.players):
            mark = col('▶', '92;1') if i == self.turn else ' '
            line = f" {mark} {p.name:<6} {LEVEL_NAME[p.level]:<8} {len(p.hand)} cartas"
            if self.reveal_all and p.is_bot:
                line += f"   {hand_str(p.hand)}  " + col(CAT_NAME[best_hand(p.hand)[0][0]], '2')
            L.append(line)
        L += ['', col(' MERCADO', '1')]
        if not self.market:
            L.append('   (vazio)')
        for j, l in enumerate(self.market, 1):
            L.append(f"   [{j}] {l.owner.name}: {card_str(l.card)} → quer {attr_str(l.want)}"
                     + (col('  (saindo)', '33') if l.removing else ''))
        if self.human:
            listed = {l.card for l in self.market if l.owner is self.human}
            view = sort_view(self.human.hand)
            parts = [f"{k}:{card_str(c)}{col('*', '33') if c in listed else ''}" for k, c in enumerate(view, 1)]
            L += ['', col(' SUA MÃO', '1') + col(f"   {CAT_NAME[best_hand(view)[0][0]]}", '2')
                  + (col('   (* = no mercado)', '2') if listed else ''), '   ' + '   '.join(parts)]
        L.append(col('─' * cols, '90'))
        plines = prompt.split('\n') if prompt else []
        room = rows - len(L) - len(plines) - 3
        vis = [m for m, only in self.logs if only is None or self.reveal_all or only is self.human]
        shown = vis[-room:] if room > 0 else []
        L += [' ' + m for m in shown] + [''] * max(0, room - len(shown))
        L.append(col('─' * cols, '90'))
        L += plines
        sys.stdout.write('\033[H\033[2J' + '\n'.join(L) + '\n')
        sys.stdout.flush()

    # ── regras ──
    def rules_lines(self):
        B = lambda t: col(t, '1;96')
        if self.freeze:
            mao_extra = "Quem pediu fica congelado: não joga nem troca até a revelação."
        else:
            mao_extra = "Quem pediu continua jogando nas voltas intermediárias, mas não pode pedir de novo."
        pedido = {'off': None,
                  'total': "Regra extra ativa: proibido pedir um naipe ou número que você tem na mão.",
                  'leve': "Regra extra ativa: proibido pedir um número do qual você já tem 2 ou mais."}[self.own_want]
        L = [B('OBJETIVO'),
             '  Terminar com a melhor mão de poker (5 cartas, escolhidas entre as que você tem).',
             '',
             B('CARTAS'),
             '  Baralho de 52 cartas + 2 coringas (JK). Cada jogador começa com 6 cartas.',
             '  O coringa não vale nada na revelação: serve só para mentir (veja abaixo).',
             '',
             B('SUA VEZ'),
             '  Você faz UMA ação:',
             '   [1] Troca na hora — anuncia à mesa o que oferece e o que quer. Cada lado é um naipe',
             '       OU um número, nunca os dois. Os outros respondem em ordem, a partir de quem está',
             '       depois de você; o primeiro que aceitar faz a troca. Se ninguém aceitar, a ação é gasta.',
             '   [2] Troca com o banco — joga uma carta no cemitério (virada para cima) e compra uma',
             '       carta aleatória do banco.',
             '   [4] Aceitar oferta do mercado — entrega uma carta que atende ao pedido e leva a carta exposta.',
             '   [5] Pedir MÃO — anuncia que quer revelar (veja abaixo).',
             '  Sem gastar ação, quantas vezes quiser:',
             '   [3] Colocar no mercado — deixa uma carta à vista com o que você quer por ela. Ela fica',
             '       lá até alguém aceitar ou você retirar. Continua sendo sua e conta na revelação.',
             '       Não dá para pôr coringa, e você precisa manter ao menos uma carta fora do mercado.',
             '   [r] Anunciar retirada — a carta sai do mercado no início da sua próxima vez;',
             '       até lá, ainda pode ser aceita.',
             '   [h] Ver estas regras.',
             '',
             B('NÃO HÁ MENTIRA... EXCETO COM O CORINGA'),
             '  Toda troca precisa ser cumprida de verdade: quem aceita entrega uma carta que atende ao',
             '  pedido. A exceção é o coringa: quem tem um pode entregá-lo no lugar da carta prometida.',
             '  Quem recebe o coringa joga ele no cemitério (todos veem) e compra uma carta do banco.',
             '',
             B('CEMITÉRIO E BANCO'),
             '  Só a carta do topo do cemitério fica visível; o resto não pode ser consultado.',
             '  Se o banco acabar, o cemitério (menos o topo) é embaralhado e vira o novo banco.',
             '',
             B('PEDIR MÃO'),
             f"  Depois do pedido, o jogo segue por mais {self.mao_rounds} volta(s). Quando a vez volta a quem",
             '  pediu pela última vez, todos revelam e a melhor mão vence. Empate divide a vitória.',
             '  ' + mao_extra,
             f"  Se ninguém pedir, a revelação é forçada ao fim da rodada {self.max_rounds}.",
             '',
             B('RANKING DAS MÃOS (da mais forte para a mais fraca)'),
             '  Straight flush > Quadra > Full house > Flush > Sequência > Trinca > Dois pares > Par > Carta alta',
             '  O ás vale alto, ou baixo na sequência A-2-3-4-5.',
             '',
             B('COMO DIGITAR NAIPES E NÚMEROS'),
             '  Naipe: c = copas ♥   o = ouros ♦   e = espadas ♠   p = paus ♣',
             '  Número: 2 a 10, J, Q, K, A']
        if pedido:
            L += ['', col(pedido, '93')]
        return L

    def show_rules(self):
        lines = self.rules_lines()
        page = 0
        while True:
            cols, rows = shutil.get_terminal_size((100, 32))
            per = max(5, rows - 4)
            pages = max(1, -(-len(lines) // per))
            page = min(page, pages - 1)
            chunk = lines[page * per:(page + 1) * per]
            head = col(f" REGRAS — página {page + 1}/{pages} ".center(cols, '═'), '1;36')
            foot = col(' [Enter] próxima   [v] voltar página   [q] fechar', '90')
            sys.stdout.write('\033[H\033[2J' + '\n'.join([head] + chunk + [''] * (per - len(chunk)) + [foot]) + '\n')
            sys.stdout.flush()
            try:
                s = input(' > ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                raise Quit
            if s == 'q' or (s == '' and page == pages - 1):
                return
            page = max(0, page - 1) if s == 'v' else page + 1

    # ── entrada humana ──
    def ask(self, prompt):
        self.render(prompt)
        try:
            return input(' > ').strip()
        except (EOFError, KeyboardInterrupt):
            raise Quit

    def choose(self, title, labels, allow_back=True):
        lines = [title] + [f"  [{i}] {lab}" for i, lab in enumerate(labels, 1)]
        if allow_back:
            lines.append('  [0] voltar / recusar')
        while True:
            s = self.ask('\n'.join(lines))
            if allow_back and s in ('', '0'):
                return None
            if s.isdigit() and 1 <= int(s) <= len(labels):
                return int(s) - 1

    def ask_attr(self, title):
        while True:
            s = self.ask(title + "\n  naipe: c=copas♥ o=ouros♦ e=espadas♠ p=paus♣   número: 2-10 J Q K A   (vazio = voltar)")
            if not s:
                return None
            a = parse_attr(s)
            if a:
                return a

    def pick_card(self, title, cards):
        view = sort_view(cards)
        i = self.choose(title, [card_str(c) for c in view])
        return None if i is None else view[i]

    def human_respond(self, t, offerer, offer, want):
        title = col(f"{offerer.name} te propõe: oferece {attr_str(offer)}, quer {attr_str(want)}.", '1;96')
        cands = self.give_cands(t, want)
        if not cands:
            self.ask(title + "\n  Você não tem carta livre válida — recusa automática. [Enter]")
            return None
        i = self.choose(title + "\n  Qual carta você entrega? (0 = recusar)",
                        [card_str(c) + (' (mentira com coringa!)' if is_joker(c) else '') for c in cands])
        return None if i is None else cands[i]

    def human_turn(self, p):
        while True:
            menu = [col(' Sua vez!', '1;92') + (f"   {self.flash}" if self.flash else ''),
                    '  [1] Troca na hora     [2] Troca com o banco     [4] Aceitar oferta do mercado'
                    + ('     [5] Pedir MÃO' if self.caller is None else ''),
                    '  Grátis:  [3] Colocar no mercado     [r] Anunciar retirada do mercado     [h] Regras     [q] Sair']
            self.flash = ''
            s = self.ask('\n'.join(menu)).lower()
            if s == '1' and self.h_trade(p): return
            if s == '2' and self.h_bank(p): return
            if s == '3':
                self.h_place(p)
            if s == '4' and self.h_accept(p): return
            if s == '5' and self.caller is None:
                self.do_call(p); return
            if s == 'r':
                self.h_remove(p)
            if s == 'h':
                self.show_rules()
            if s == 'q':
                raise Quit

    def h_trade(self, p):
        offer = self.ask_attr('O que você OFERECE? (naipe OU número)')
        if offer is None:
            return False
        if not self.give_cands(p, offer):
            self.flash = col(f"Você não tem carta livre de {attr_str(offer)} nem coringa.", '91')
            return False
        want = self.ask_attr('O que você QUER? (naipe OU número)')
        if want is None:
            return False
        if not self.want_ok(p, want):
            self.flash = col(f"Regra: você não pode pedir {attr_str(want)}.", '91')
            return False
        self.do_trade(p, offer, want, None)
        return True

    def h_bank(self, p):
        c = self.pick_card('Qual carta vai para o cemitério?', self.free(p))
        if c is None:
            return False
        self.do_bank(p, c)
        return True

    def h_place(self, p):
        if len(self.free(p)) <= 1:
            self.flash = col('Você precisa manter ao menos uma carta fora do mercado.', '91')
            return False
        c = self.pick_card('Qual carta vai para o mercado?', [c for c in self.free(p) if not is_joker(c)])
        if c is None:
            return False
        want = self.ask_attr(f"O que você quer em troca de {card_str(c)}? (naipe OU número)")
        if want is None:
            return False
        if not self.want_ok(p, want):
            self.flash = col(f"Regra: você não pode pedir {attr_str(want)}.", '91')
            return False
        self.do_place(p, c, want)
        return True

    def h_accept(self, p):
        ls = [l for l in self.market if l.owner is not p and not self.frozen(l.owner)]
        if not ls:
            self.flash = col('Nenhuma oferta de outros jogadores no mercado.', '91')
            return False
        i = self.choose('Qual oferta?', [f"{l.owner.name}: {card_str(l.card)} → quer {attr_str(l.want)}" for l in ls])
        if i is None:
            return False
        l = ls[i]
        cands = self.give_cands(p, l.want)
        if not cands:
            self.flash = col(f"Você não tem {attr_str(l.want)} livre nem coringa.", '91')
            return False
        j = self.choose('Qual carta você entrega?',
                        [card_str(c) + (' (mentira com coringa!)' if is_joker(c) else '') for c in cands])
        if j is None:
            return False
        self.do_accept(p, l, cands[j])
        return True

    def h_remove(self, p):
        ls = [l for l in self.market if l.owner is p and not l.removing]
        if not ls:
            self.flash = col('Você não tem cartas no mercado para retirar.', '91')
            return
        i = self.choose('Retirar qual? (sai no início da sua próxima vez)', [card_str(l.card) for l in ls])
        if i is not None:
            self.announce_removal(p, ls[i])


# ───────────────────────────── bots ─────────────────────────────
def unknown_pool(g, p):
    """Cartas que o bot acha que podem estar no banco/mãos alheias."""
    excl = set(p.hand)
    if p.level == 'dificil':                      # lembra tudo o que viu
        excl |= p.memory | {l.card for l in g.market}
    elif p.level == 'medio':                      # só o que está visível agora
        excl |= {l.card for l in g.market}
        if g.grave:
            excl.add(g.grave[-1])
    return [c for c in FULL_DECK if c not in excl]


def best_want(pool, vs, attrs=ALL_ATTRS):
    best, bev = None, -1.0
    for w in attrs:
        m = [v for x, v in zip(pool, vs) if matches(x, w)]
        if m:
            ev = sum(m) / len(m)
            if ev > bev:
                best, bev = w, ev
    return best, bev


def offer_attr(rng, card):
    if is_joker(card):                            # mentira: anuncia qualquer coisa
        return rng.choice(ALL_ATTRS)
    return ('rank', card[0]) if rng.random() < 0.5 else ('suit', card[1])


def easy_action(g, p, free, others):
    rng = g.rng
    if g.caller is None and g.round >= 3 and rng.random() < 0.08 + 0.04 * g.round:
        return ('call',)
    if not free:
        return ('pass',)
    _, best = best_hand(p.hand)
    junk = [c for c in free if c not in best] or free
    if not junk:
        return ('pass',)
    r = rng.random()
    if r < 0.5:
        return ('bank', rng.choice(junk))
    if r < 0.8:
        c = rng.choice(junk)
        return ('trade', offer_attr(rng, c), rng.choice(g.allowed_wants(p)), c)
    accepts = [(l, c) for l in g.market if l.owner is not p and not g.frozen(l.owner) for c in junk if matches(c, l.want)]
    if accepts and r < 0.9:
        l, c = rng.choice(accepts)
        return ('accept', l, c)
    return ('bank', rng.choice(junk))


def choose_action(g, p):
    rng, lv = g.rng, p.level
    free = g.free(p)
    others = [o for o in g.players if o is not p]
    free_listing(g, p, unknown_pool(g, p))
    free = g.free(p)
    if lv == 'facil':
        return easy_action(g, p, free, others)

    cur = score(p.hand)
    cat = int(cur)
    # retirar do mercado carta que virou importante
    for l in g.market:
        if l.owner is p and not l.removing and score([c for c in p.hand if c != l.card]) < cur - 0.5:
            g.announce_removal(p, l)

    pool = unknown_pool(g, p)
    vals = {c: [score([h for h in p.hand if h != c] + [x]) for x in pool] for c in free}
    noise = (lambda: rng.gauss(0, 0.08)) if lv == 'medio' else (lambda: 0.0)
    opts = []
    for c, vs in vals.items():
        opts.append((sum(vs) / len(vs) + noise(), ('bank', c)))
        if is_joker(c) and lv == 'medio' and rng.random() < 0.5:
            continue                               # médio nem sempre tem coragem de mentir
        w, wev = best_want(pool, vs, g.allowed_wants(p))
        if w is None:
            continue
        # chance de pelo menos alguém da mesa aceitar
        miss = 1.0
        for t in others:
            if lv == 'dificil':
                a, n = p.stats.get(t.name, [0, 0])
                miss *= 1 - (a + 0.5) / (n + 4)       # começa supondo ~12% de aceite e aprende na partida
            else:
                miss *= 0.85
        pa = 1 - miss
        opts.append((pa * wev + (1 - pa) * cur + noise(), ('trade', offer_attr(rng, c), w, c)))
    for l in g.market:
        if l.owner is p or g.frozen(l.owner):
            continue
        for c in free:
            if matches(c, l.want) or (is_joker(c) and lv == 'dificil'):
                opts.append((score([h for h in p.hand if h != c] + [l.card]) + noise(), ('accept', l, c)))

    if not opts:
        return dead_offer(g, p, pool, free)
    best_ev, best_act = max(opts, key=lambda o: o[0])
    gain = best_ev - cur
    if g.caller is None:
        if lv == 'medio':
            if cat >= 3 or (cat >= 2 and g.round >= 5) or g.round >= 10:
                return ('call',)
        else:
            if (cat >= 4 or (cat >= 3 and gain < 0.4) or (cat >= 2 and gain < 0.12 and g.round >= 4)
                    or (cat >= 1 and g.round >= 12)):
                return ('call',)
    if gain <= 0.01:                                  # nada melhora: "pular" com oferta quase impossível
        return dead_offer(g, p, pool, free)
    return best_act


def free_listing(g, p, pool):
    """Colocar no mercado é grátis: médio/difícil sempre deixam a carta sobrando à venda."""
    if any(l.owner is p for l in g.market) or g.caller is not None:
        return
    free = g.free(p)
    real = [c for c in free if not is_joker(c)]
    if len(free) <= 2 or not real:
        return
    if p.level == 'facil':
        if g.rng.random() < 0.3:
            g.do_place(p, g.rng.choice(real), g.rng.choice(g.allowed_wants(p)))
        return
    spare = max(real, key=lambda c: score([h for h in p.hand if h != c]))
    rest = [h for h in p.hand if h != spare]
    w, _ = best_want(pool, [score(rest + [x]) for x in pool], g.allowed_wants(p))
    if w:
        g.do_place(p, spare, w)


def dead_offer(g, p, pool, free):
    """Troca na hora feita para ser recusada: pede o atributo que quase não existe fora da sua mão
    (ex.: pede um 2 tendo um par de 2; pede um 4 depois de ver três 4 no cemitério)."""
    if not free:
        return ('pass',)
    give = max(free, key=lambda c: score([h for h in p.hand if h != c]))   # a que menos dói perder
    rest = [h for h in p.hand if h != give]
    def key(w):
        out = [x for x in pool if matches(x, w)]
        ev = sum(score(rest + [x]) for x in out) / len(out) if out else 0
        return (len(out), -ev)
    want = min(g.allowed_wants(p), key=key)
    return ('trade', offer_attr(g.rng, give), want, give)


def bot_respond(g, t, offerer, offer, want):
    rng, lv = g.rng, t.level
    free = g.free(t)
    cands = [c for c in free if matches(c, want)]
    jok = [c for c in free if is_joker(c)]
    if lv == 'dificil' or (lv == 'medio' and rng.random() < 0.5) or (lv == 'facil' and rng.random() < 0.3):
        cands += jok
    if not cands:
        return None
    if lv == 'facil':
        return rng.choice(cands) if rng.random() < 0.5 else None
    pool = unknown_pool(g, t)
    inc = [x for x in pool if matches(x, offer)]
    if not inc:
        return None
    cur = score(t.hand)
    best, bev = None, -1.0
    for c in cands:
        rest = [h for h in t.hand if h != c]
        ev = sum(score(rest + [x]) for x in inc) / len(inc)
        if lv == 'dificil':                       # risco de receber coringa (mentira)
            jk = sum(1 for x in pool if is_joker(x))
            if jk:
                risk = 0.12 * jk
                ev = (1 - risk) * ev + risk * sum(score(rest + [x]) for x in pool) / len(pool)
        if ev > bev:
            best, bev = c, ev
    margin = 0.03 if lv == 'medio' else 0.0
    return best if bev > cur + margin else None


# ───────────────────────────── main ─────────────────────────────
ALIASES = {'facil': 'facil', 'fácil': 'facil', 'f': 'facil', 'easy': 'facil',
           'medio': 'medio', 'médio': 'medio', 'm': 'medio', 'medium': 'medio',
           'dificil': 'dificil', 'difícil': 'dificil', 'd': 'dificil', 'hard': 'dificil'}


OWN = {'livre': 'off', 'total': 'total', 'leve': 'leve'}


def run_sim(levels, n, max_rounds, seed, mao=3, freeze=False, own='off'):
    rng = random.Random(seed)
    wins, rounds, cats = Counter(), 0, Counter()
    t0 = time.time()
    for i in range(n):
        g = Game(levels, human=False, show=False, max_rounds=max_rounds, rng=rng, mao_rounds=mao,
                 freeze=freeze, own_want=own)
        winners = g.play()
        for w in winners:
            wins[w.name] += 1 / len(winners)
            cats[best_hand(w.hand)[0][0]] += 1 / len(winners)
        rounds += min(g.round, max_rounds)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{n} partidas...", file=sys.stderr)
    print(f"\n{n} partidas em {time.time() - t0:.1f}s — média de {rounds / n:.1f} rodadas\n")
    for i, lv in enumerate(levels):
        name = f"Bot{i + 1}"
        print(f"  {name} ({LEVEL_NAME[lv]:<7})  {wins[name]:7.1f} vitórias  {100 * wins[name] / n:5.1f}%")
    print("\n  Mão vencedora:")
    for k in sorted(cats, reverse=True):
        print(f"    {CAT_NAME[k]:<15} {100 * cats[k] / n:5.1f}%")


def main():
    global USE_COLOR
    ap = argparse.ArgumentParser(description='Poquertini no terminal')
    ap.add_argument('--bots', default='facil,medio,dificil')
    ap.add_argument('--assistir', action='store_true')
    ap.add_argument('--simular', type=int, default=0)
    ap.add_argument('--delay', type=float, default=1.2)
    ap.add_argument('--rodadas', type=int, default=30)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--sem-cor', action='store_true')
    ap.add_argument('--congelar', action='store_true', help='quem pede Mão não joga nem troca até a revelação')
    ap.add_argument('--pedido', choices=['livre', 'total', 'leve'], default='livre',
                    help="total: proibido pedir atributo que você tem; leve: proibido pedir número de que já tem 2+")
    ap.add_argument('--mao-rodadas', type=int, default=3, help='voltas jogadas depois de pedir Mão (1, 2, 3...)')
    a = ap.parse_args()
    try:
        levels = [ALIASES[x.strip().lower()] for x in a.bots.split(',') if x.strip()]
    except KeyError as e:
        sys.exit(f"Nível desconhecido: {e}. Use facil, medio ou dificil.")
    human = not (a.assistir or a.simular)
    if not 2 <= len(levels) + human <= 7:
        sys.exit("O jogo precisa de 2 a 7 jogadores.")
    if os.name == 'nt':
        os.system('')
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    USE_COLOR = not a.sem_cor
    if a.simular:
        USE_COLOR = False
        run_sim(levels, a.simular, a.rodadas, a.seed, a.mao_rodadas, a.congelar, OWN[a.pedido])
        return

    rng = random.Random(a.seed)
    tally = Counter()
    sys.stdout.write('\033[?1049h')
    try:
        while True:
            g = Game(levels, human=human, reveal=a.assistir, delay=a.delay, max_rounds=a.rodadas, rng=rng,
                     mao_rounds=a.mao_rodadas, freeze=a.congelar, own_want=OWN[a.pedido])
            winners = g.play()
            for w in winners:
                tally[w.name] += 1 / len(winners)
            placar = '   '.join(f"{p.name}: {tally[p.name]:g}" for p in g.players)
            if g.ask(f" Placar — {placar}\n Jogar de novo? (s/n)").lower().startswith('n'):
                break
    except Quit:
        pass
    finally:
        sys.stdout.write('\033[?1049l')
        sys.stdout.flush()
    print("Até a próxima!")


if __name__ == '__main__':
    main()
