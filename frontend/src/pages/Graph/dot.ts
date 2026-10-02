// The API emits a small, line-oriented subset of DOT, not arbitrary Graphviz.
// Reject unsupported syntax rather than silently drawing an incomplete graph.
export interface DotNode {
  id: string;
  label: string;
  shape: string;
  fill: string;
  color: string;
}

export interface DotEdge {
  source: string;
  target: string;
  label: string;
}

export interface DotGraph {
  directed: boolean;
  nodes: DotNode[];
  edges: DotEdge[];
}

const identifier = '[^\\s\\[\\]{};,=]+';
const nodePattern = new RegExp(`^(${identifier})\\s*\\[(.*)\\]$`);
const edgePattern = new RegExp(`^(${identifier})\\s*(--|->)\\s*(${identifier})(?:\\s*\\[(.*)\\])?$`);
const safeColor = (value: string | undefined, fallback: string) =>
  value && (/^#[0-9a-fA-F]{3,8}$/.test(value) || /^(white|black|red|gray|grey)$/.test(value))
    ? value : fallback;

function attributes(raw: string): Record<string, string> {
  const result: Record<string, string> = {};
  let pos = 0;
  while (pos < raw.length) {
    const match = /^\s*([a-zA-Z_]+)\s*=\s*(?:"((?:\\.|[^"\\])*)"|([^,\s]+))\s*(,|$)/.exec(raw.slice(pos));
    if (!match) throw new Error('DOT 属性格式无效');
    result[match[1]] = match[2] ?? match[3];
    pos += match[0].length;
  }
  return result;
}

function label(value: string): string {
  return value.replace(/\\n/g, '\n').replace(/\\"/g, '"')
    .replace(/&(amp|lt|gt|quot|#63|#123|#125|#124);/g, (_, entity: string) =>
      ({ amp: '&', lt: '<', gt: '>', quot: '"', '#63': '?', '#123': '{', '#125': '}', '#124': '|' })[entity] || '');
}

export function parseDot(dot: unknown): DotGraph {
  if (typeof dot !== 'string' || !dot.trim()) throw new Error('接口未返回 DOT 图谱内容');
  if (dot.length > 200_000) throw new Error('DOT 图谱过大，无法显示');
  const lines = dot.trim().split(/\r?\n/);
  const header = /^(di)?graph\s+[^\s{}]+\s*\{$/.exec(lines.shift()?.trim() || '');
  if (!header || lines.pop()?.trim() !== '}') throw new Error('DOT 图谱格式无效');
  const directed = !!header[1];
  const nodes = new Map<string, DotNode>();
  const edges: DotEdge[] = [];
  for (const line of lines) {
    const statement = line.trim();
    if (!statement) continue;
    if (!statement.endsWith(';')) throw new Error('DOT 语句缺少结束符');
    const body = statement.slice(0, -1).trim();
    if (/^(rankdir|bgcolor)\s*=/.test(body) || /^(node|edge)\s*\[/.test(body)) continue;
    const edge = edgePattern.exec(body);
    if (edge) {
      if (edge[2] !== (directed ? '->' : '--')) throw new Error('DOT 边类型无效');
      edges.push({ source: edge[1], target: edge[3], label: label(attributes(edge[4] || '').label || '') });
      if (edges.length > 1500) throw new Error('图谱边数超过显示上限');
      continue;
    }
    const node = nodePattern.exec(body);
    if (!node) throw new Error('DOT 包含不支持的语句');
    const attrs = attributes(node[2]);
    nodes.set(node[1], {
      id: node[1], label: label(attrs.label || node[1]),
      shape: attrs.shape || 'box',
      fill: safeColor(attrs.fillcolor, '#1565C0'),
      color: safeColor(attrs.fontcolor, 'white'),
    });
    if (nodes.size > 300) throw new Error('图谱节点数超过显示上限');
  }
  for (const edge of edges) {
    for (const id of [edge.source, edge.target]) {
      if (!nodes.has(id)) nodes.set(id, { id, label: id, shape: 'box', fill: '#1565C0', color: 'white' });
    }
  }
  if (nodes.size > 300) throw new Error('图谱节点数超过显示上限');
  return { directed, nodes: [...nodes.values()], edges };
}
