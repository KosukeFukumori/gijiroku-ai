"""議事録・文字起こしの PDF 出力。

reportlab で PDF を組む。日本語フォントは reportlab 内蔵の CID フォント
（HeiseiMin-W3 / HeiseiKakuGo-W5）を使う。macOS のヒラギノ等は PostScript
アウトライン（CFF）の .ttc で reportlab が埋め込めないため、フォントファイルに
依存しない CID フォントを採用している。本文は明朝、見出し・強調はゴシックに
割り当てることで、太字グリフを持たない CID フォントでも字面の差が付く。
"""

import html
import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from markdown_it import MarkdownIt
from markdown_it.token import Token
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    ListFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from gijiroku_ai.models import RecordingDetail, Segment

FONT_SERIF = "HeiseiMin-W3"  # 本文（明朝）
FONT_SANS = "HeiseiKakuGo-W5"  # 見出し・強調（ゴシック）

JST = ZoneInfo("Asia/Tokyo")

# 表示色（画面の暗色テーマとは別に、印刷前提の明るい配色にする）
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#d4d4d8")
BAND = colors.HexColor("#f4f4f5")

PAGE_MARGIN = 18 * mm
# 文字起こしの表を一度に組むと行数が多い録音で重くなるため、この件数ごとに分割する
TRANSCRIPT_CHUNK = 60

_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_SERIF))
    pdfmetrics.registerFont(UnicodeCIDFont(FONT_SANS))
    # CID フォントには太字・斜体のグリフが無いので、<b>/<i> はゴシックへ寄せる
    pdfmetrics.registerFontFamily(
        FONT_SERIF,
        normal=FONT_SERIF,
        bold=FONT_SANS,
        italic=FONT_SERIF,
        boldItalic=FONT_SANS,
    )
    pdfmetrics.registerFontFamily(
        FONT_SANS,
        normal=FONT_SANS,
        bold=FONT_SANS,
        italic=FONT_SANS,
        boldItalic=FONT_SANS,
    )
    _fonts_ready = True


@dataclass(frozen=True)
class _Styles:
    """PDF 内で使う段落スタイル一式。"""

    doc_title: ParagraphStyle
    doc_meta: ParagraphStyle
    h1: ParagraphStyle
    h2: ParagraphStyle
    h3: ParagraphStyle
    body: ParagraphStyle
    list_item: ParagraphStyle
    quote: ParagraphStyle
    code: ParagraphStyle
    table_cell: ParagraphStyle
    table_head: ParagraphStyle
    seg_time: ParagraphStyle
    seg_speaker: ParagraphStyle
    seg_text: ParagraphStyle


def _build_styles() -> _Styles:
    base = ParagraphStyle(
        "body",
        fontName=FONT_SERIF,
        fontSize=10,
        leading=16.5,
        textColor=INK,
        alignment=TA_LEFT,
        spaceAfter=6,
        # 日本語は単語区切りが無いため、はみ出しを避けて任意位置で折り返す
        wordWrap="CJK",
    )
    heading = ParagraphStyle(
        "h",
        parent=base,
        fontName=FONT_SANS,
        keepWithNext=1,
        spaceBefore=12,
        spaceAfter=5,
    )
    return _Styles(
        doc_title=ParagraphStyle(
            "doc_title",
            parent=base,
            fontName=FONT_SANS,
            fontSize=17,
            leading=24,
            spaceAfter=4,
        ),
        doc_meta=ParagraphStyle(
            "doc_meta",
            parent=base,
            fontSize=8.5,
            leading=14,
            textColor=MUTED,
            spaceAfter=0,
        ),
        h1=ParagraphStyle("h1", parent=heading, fontSize=14, leading=21),
        h2=ParagraphStyle("h2", parent=heading, fontSize=12.5, leading=19),
        h3=ParagraphStyle("h3", parent=heading, fontSize=11, leading=17),
        body=base,
        list_item=ParagraphStyle("list_item", parent=base, spaceAfter=2),
        quote=ParagraphStyle(
            "quote",
            parent=base,
            leftIndent=8 * mm,
            textColor=MUTED,
            borderPadding=0,
        ),
        code=ParagraphStyle(
            "code",
            parent=base,
            fontName="Courier",
            fontSize=8.5,
            leading=12.5,
            leftIndent=4 * mm,
            textColor=colors.HexColor("#334155"),
            wordWrap=None,
        ),
        table_cell=ParagraphStyle(
            "table_cell", parent=base, fontSize=9, leading=14, spaceAfter=0
        ),
        table_head=ParagraphStyle(
            "table_head",
            parent=base,
            fontName=FONT_SANS,
            fontSize=9,
            leading=14,
            spaceAfter=0,
        ),
        seg_time=ParagraphStyle(
            "seg_time",
            parent=base,
            fontName="Courier",
            fontSize=8.5,
            leading=15,
            textColor=MUTED,
            spaceAfter=0,
        ),
        seg_speaker=ParagraphStyle(
            "seg_speaker",
            parent=base,
            fontName=FONT_SANS,
            fontSize=8.5,
            leading=15,
            textColor=MUTED,
            spaceAfter=0,
        ),
        seg_text=ParagraphStyle("seg_text", parent=base, leading=15.5, spaceAfter=0),
    )


def _styles() -> _Styles:
    _register_fonts()
    return _build_styles()


# ============================================================
# 文字列フォーマット
# ============================================================


def _format_datetime(iso: str) -> str:
    """UTC の ISO8601 文字列を JST の読みやすい表記にする。"""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")


def _format_duration(sec: float | None) -> str:
    if sec is None:
        return "-"
    total = round(sec)
    return f"{total // 3600:d}:{total // 60 % 60:02d}:{total % 60:02d}"


def _format_timestamp(sec: float) -> str:
    """発話位置を mm:ss（1時間以上なら h:mm:ss）にする。"""
    total = int(sec)
    if total >= 3600:
        return f"{total // 3600:d}:{total // 60 % 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def safe_filename(title: str) -> str:
    """ファイル名に使えない文字を落とし、長すぎる場合は切り詰める。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", title).strip(" .")
    return (cleaned or "recording")[:60]


# ============================================================
# Markdown → reportlab のフロー要素
# ============================================================

# 既定（commonmark）では表が無効なので、GFM の表と打ち消し線を足す
_md = MarkdownIt().enable(["table", "strikethrough"])


def _list_flowable(
    items: list[list[Flowable]], kind: str, *, spaced: bool
) -> ListFlowable:
    """箇条書き・番号付きリストを組む（1項目 = フロー要素のリスト）。"""
    return ListFlowable(
        items,
        bulletType=kind,
        start="•" if kind == "bullet" else 1,
        bulletFontName="Helvetica",
        bulletFontSize=8,
        leftIndent=7 * mm,
        spaceAfter=6 if spaced else 2,
    )


def _inline_markup(tokens: list[Token]) -> str:
    """inline トークン列を reportlab の簡易 HTML 文字列にする。"""
    parts: list[str] = []
    for tok in tokens:
        if tok.type == "text":
            parts.append(html.escape(tok.content))
        elif tok.type == "code_inline":
            parts.append(f'<font face="Courier">{html.escape(tok.content)}</font>')
        elif tok.type in ("strong_open", "strong_close"):
            parts.append("<b>" if tok.type == "strong_open" else "</b>")
        elif tok.type in ("em_open", "em_close"):
            parts.append("<i>" if tok.type == "em_open" else "</i>")
        elif tok.type in ("s_open", "s_close"):
            parts.append("<strike>" if tok.type == "s_open" else "</strike>")
        elif tok.type == "link_open":
            href = html.escape(str(tok.attrGet("href") or ""))
            parts.append(f'<link href="{href}" color="#2563eb">')
        elif tok.type == "link_close":
            parts.append("</link>")
        elif tok.type == "softbreak":
            # 日本語では改行位置に空白を入れたくないが、英単語同士は繋げたくない
            prev = parts[-1][-1] if parts and parts[-1] else ""
            parts.append(" " if prev.isascii() and prev.isalnum() else "")
        elif tok.type == "hardbreak":
            parts.append("<br/>")
        elif tok.type == "image":
            alt = html.escape(tok.content or "画像")
            parts.append(f"[{alt}]")
        elif tok.children:
            parts.append(_inline_markup(tok.children))
    return "".join(parts)


def _table_flowable(rows: list[list[str]], width: float, st: _Styles) -> Flowable:
    """GFM テーブルを Table にする（1 行目をヘッダ扱いにする）。"""
    cols = max(len(r) for r in rows)
    col_width = width / cols
    data = [
        [
            Paragraph(cell, st.table_head if i == 0 else st.table_cell)
            for cell in (row + [""] * (cols - len(row)))
        ]
        for i, row in enumerate(rows)
    ]
    table = Table(data, colWidths=[col_width] * cols, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, RULE),
                ("BACKGROUND", (0, 0), (-1, 0), BAND),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def markdown_flowables(
    markdown: str, width: float, st: _Styles | None = None
) -> list[Flowable]:
    """Markdown 本文を reportlab のフロー要素に変換する。

    見出し・段落・箇条書き（入れ子可）・引用・コードブロック・水平線・
    GFM テーブルに対応する。未知の構造は段落として素直に流す。
    """
    st = st or _styles()
    tokens = _md.parse(markdown or "")
    heading_styles = {"h1": st.h1, "h2": st.h2, "h3": st.h3}

    flow: list[Flowable] = []
    # 箇条書きは入れ子になるため、リストごとに積み上げる。各リストは
    # 「1項目 = フロー要素のリスト」で持つ（ListFlowable は要素リストを渡すと
    # 先頭だけに行頭記号を付けるので、入れ子リストに記号が二重に付かない）
    list_stack: list[tuple[str, list[list[Flowable]]]] = []
    # テーブル組み立て中の状態
    table_rows: list[list[str]] = []
    row: list[str] = []
    in_table = False
    in_quote = False

    def emit(item: Flowable) -> None:
        """フロー要素を、リストの中なら現在の項目へ、そうでなければ本体へ追加する。"""
        if list_stack:
            items = list_stack[-1][1]
            if not items:
                items.append([])
            items[-1].append(item)
        else:
            flow.append(item)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == "heading_open":
            style = heading_styles.get(tok.tag, st.h3)
            emit(Paragraph(_inline_markup(tokens[i + 1].children or []), style))
            i += 3
            continue
        if tok.type == "inline":
            text = _inline_markup(tok.children or [])
            if in_table:
                row.append(text)
            elif text:
                emit(Paragraph(text, st.quote if in_quote else st.body))
            i += 1
            continue
        if tok.type in ("bullet_list_open", "ordered_list_open"):
            list_stack.append(("bullet" if tok.type == "bullet_list_open" else "1", []))
            i += 1
            continue
        if tok.type == "list_item_open":
            list_stack[-1][1].append([])
            i += 1
            continue
        if tok.type in ("bullet_list_close", "ordered_list_close"):
            kind, items = list_stack.pop()
            items = [item for item in items if item]
            if items:
                nested = bool(list_stack)
                lst = _list_flowable(items, kind, spaced=not nested)
                if nested:
                    emit(lst)
                else:
                    flow.append(lst)
            i += 1
            continue
        if tok.type in ("code_block", "fence"):
            lines = html.escape(tok.content.rstrip("\n")).replace(" ", "&nbsp;")
            emit(Paragraph(lines.replace("\n", "<br/>"), st.code))
            i += 1
            continue
        if tok.type == "blockquote_open":
            in_quote = True
            i += 1
            continue
        if tok.type == "blockquote_close":
            in_quote = False
            i += 1
            continue
        if tok.type == "hr":
            emit(
                HRFlowable(
                    width="100%", thickness=0.5, color=RULE, spaceBefore=6, spaceAfter=8
                )
            )
            i += 1
            continue
        if tok.type == "table_open":
            in_table, table_rows = True, []
            i += 1
            continue
        if tok.type == "tr_open":
            row = []
            i += 1
            continue
        if tok.type == "tr_close":
            table_rows.append(row)
            i += 1
            continue
        if tok.type == "table_close":
            in_table = False
            if table_rows:
                emit(_table_flowable(table_rows, width, st))
                emit(Spacer(1, 6))
            i += 1
            continue
        i += 1

    return flow


# ============================================================
# ドキュメント組み立て
# ============================================================


def _footer(doc_title: str) -> Callable[[Canvas, SimpleDocTemplate], None]:
    """各ページ下部にドキュメント名とページ番号を描く関数を返す。"""

    def draw(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont(FONT_SERIF, 8)
        canvas.setFillColor(MUTED)
        y = PAGE_MARGIN - 6 * mm
        canvas.drawString(PAGE_MARGIN, y, doc_title)
        canvas.drawRightString(A4[0] - PAGE_MARGIN, y, str(canvas.getPageNumber()))
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.4)
        canvas.line(PAGE_MARGIN, y + 4 * mm, A4[0] - PAGE_MARGIN, y + 4 * mm)
        canvas.restoreState()

    return draw


def _doc_title(detail: RecordingDetail) -> str:
    return detail.title or detail.original_filename


def _header_flowables(
    detail: RecordingDetail, kind: str, st: _Styles
) -> list[Flowable]:
    """表題（タイトル・種別・日時などのメタ情報）を作る。"""
    meta = [
        f"会議日時: {_format_datetime(detail.meeting_datetime)}",
        f"収録時間: {_format_duration(detail.duration_sec)}",
        f"出力日時: {_format_datetime(datetime.now(UTC).isoformat())}",
    ]
    return [
        Paragraph(f'<font color="#6b7280" size="9">{kind}</font>', st.doc_meta),
        Paragraph(html.escape(_doc_title(detail)), st.doc_title),
        Paragraph(html.escape(" / ".join(meta)), st.doc_meta),
        HRFlowable(
            width="100%", thickness=0.8, color=RULE, spaceBefore=8, spaceAfter=12
        ),
    ]


def _new_doc(
    detail: RecordingDetail, kind: str
) -> tuple[SimpleDocTemplate, io.BytesIO]:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=PAGE_MARGIN,
        rightMargin=PAGE_MARGIN,
        topMargin=PAGE_MARGIN,
        bottomMargin=PAGE_MARGIN,
        title=f"{_doc_title(detail)} - {kind}",
        author="議事録AI",
    )
    return doc, buffer


def _bullet_list(items: list[str], st: _Styles) -> Flowable:
    """決定事項・アクションアイテム（ただの文字列の並び）を箇条書きにする。"""
    return _list_flowable(
        [[Paragraph(html.escape(item), st.list_item)] for item in items],
        "bullet",
        spaced=True,
    )


def build_minutes_pdf(detail: RecordingDetail) -> bytes:
    """議事録（本文・決定事項・アクションアイテム）の PDF を作る。"""
    st = _styles()
    doc, buffer = _new_doc(detail, "議事録")
    flow = _header_flowables(detail, "議事録", st)

    if detail.summary:
        flow.extend(markdown_flowables(detail.summary, doc.width, st))
    else:
        flow.append(Paragraph("議事録はまだ生成されていません。", st.body))

    for heading, items in (
        ("決定事項", detail.decisions),
        ("アクションアイテム", detail.action_items),
    ):
        if not items:
            continue
        flow.append(Spacer(1, 6))
        flow.append(KeepTogether([Paragraph(heading, st.h2), _bullet_list(items, st)]))

    doc.build(
        flow,
        onFirstPage=_footer(_doc_title(detail)),
        onLaterPages=_footer(_doc_title(detail)),
    )
    return buffer.getvalue()


def _speaker_column_width(segments: list[Segment], st: _Styles) -> float:
    """話者名の列幅を実データから決める。

    「インテリアコーディネーター」のような長いラベルを狭い列に押し込むと
    何行にも折り返して行間が間延びするため、いちばん長い名前に合わせて広げる。
    ただし広げすぎると本文が痩せるので上限を設ける（2 行程度に収める）。
    """
    longest = max(
        (
            pdfmetrics.stringWidth(
                seg.speaker, st.seg_speaker.fontName, st.seg_speaker.fontSize
            )
            for seg in segments
            if seg.speaker
        ),
        default=0.0,
    )
    return min(max(longest + 6, 14 * mm), 34 * mm)


def _transcript_table(
    segments: list[Segment], width: float, speaker_w: float, st: _Styles
) -> Table:
    """文字起こしの一区間ぶんを「時間 / 話者 / 本文」の表にする。"""
    time_w = 14 * mm
    data = [
        [
            Paragraph(_format_timestamp(seg.start_sec), st.seg_time),
            Paragraph(html.escape(seg.speaker or ""), st.seg_speaker),
            Paragraph(html.escape(seg.text or ""), st.seg_text),
        ]
        for seg in segments
    ]
    table = Table(data, colWidths=[time_w, speaker_w, width - time_w - speaker_w])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
            ]
        )
    )
    return table


def build_transcript_pdf(detail: RecordingDetail) -> bytes:
    """文字起こし（時間・話者付き）の PDF を作る。"""
    st = _styles()
    doc, buffer = _new_doc(detail, "文字起こし")
    flow = _header_flowables(detail, "文字起こし", st)

    if not detail.segments:
        flow.append(Paragraph("文字起こしはまだ生成されていません。", st.body))
    else:
        # 列幅は全体で揃えたいので、分割して組む前に一度だけ決める
        speaker_w = _speaker_column_width(detail.segments, st)
        for i in range(0, len(detail.segments), TRANSCRIPT_CHUNK):
            chunk = detail.segments[i : i + TRANSCRIPT_CHUNK]
            flow.append(_transcript_table(chunk, doc.width, speaker_w, st))

    doc.build(
        flow,
        onFirstPage=_footer(_doc_title(detail)),
        onLaterPages=_footer(_doc_title(detail)),
    )
    return buffer.getvalue()


__all__ = [
    "build_minutes_pdf",
    "build_transcript_pdf",
    "safe_filename",
]
