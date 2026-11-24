import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseDot } from './dot.ts';

test('renders backend component DOT nodes, edges and escaped labels', () => {
  const graph = parseDot(`graph G {
  rankdir=LR;
  node [fontname="Arial"];
  comp_U1 [label="U1\\n(IC)", shape=box, style="filled,bold", fillcolor="#1565C0", fontcolor=white];
  net_3V3 [label="3V3 &amp; &lt;power&gt;", shape=circle, fillcolor="#e53935"];
  comp_U1 -- net_3V3 [label="PWR", fontsize=8];
}`);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.nodes[0].label, 'U1\n(IC)');
  assert.equal(graph.nodes[1].label, '3V3 & <power>');
  assert.deepEqual(graph.edges, [{ source: 'comp_U1', target: 'net_3V3', label: 'PWR' }]);
});

test('renders directed power chain and implicit nodes', () => {
  const graph = parseDot(`digraph PowerChain {
  rankdir=RL;
  U1 [label="U1\\n(起点)",fillcolor="#FFC107",fontcolor="#000"];
  U1 -> U2 [label="3.3V",color="#e53935"];
}`);
  assert.equal(graph.directed, true);
  assert.equal(graph.nodes.length, 2);
  assert.equal(graph.edges[0].target, 'U2');
});

test('empty graphs, invalid syntax and unsafe color are handled', () => {
  assert.equal(parseDot('graph G {\n}').nodes.length, 0);
  assert.throws(() => parseDot(null), /未返回/);
  assert.throws(() => parseDot('not dot'), /格式无效/);
  assert.throws(() => parseDot('graph G {\n  broken statement;\n}'), /不支持/);
  assert.equal(parseDot('graph G {\n  a [label="<script>",fillcolor="url(evil)"];\n}').nodes[0].fill, '#1565C0');
});
