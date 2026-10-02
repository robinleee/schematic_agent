import { useMemo } from 'react';
import { forceCenter, forceLink, forceManyBody, forceSimulation, forceCollide } from 'd3';
import type { DotGraph, DotNode } from './dot';

type Positioned = DotNode & { x: number; y: number };

export default function DotView({ graph }: { graph: DotGraph }) {
  const layout = useMemo(() => {
    const nodes: Positioned[] = graph.nodes.map((node) => ({ ...node, x: 0, y: 0 }));
    const links = graph.edges.map((edge) => ({ ...edge }));
    const simulation = forceSimulation(nodes)
      .force('link', forceLink<Positioned, typeof links[number]>(links).id((node) => node.id).distance(170))
      .force('charge', forceManyBody().strength(-350))
      .force('collide', forceCollide(80))
      .force('center', forceCenter(0, 0)).stop();
    for (let i = 0; i < 250; i++) simulation.tick();
    const byId = new Map(nodes.map((node) => [node.id, node]));
    const xs = nodes.map((node) => node.x);
    const ys = nodes.map((node) => node.y);
    return {
      nodes, links: graph.edges.map((edge) => ({ ...edge, from: byId.get(edge.source)!, to: byId.get(edge.target)! })),
      bounds: [Math.min(...xs) - 120, Math.min(...ys) - 100,
        Math.max(360, Math.max(...xs) - Math.min(...xs) + 240),
        Math.max(300, Math.max(...ys) - Math.min(...ys) + 200)].join(' '),
    };
  }, [graph]);

  return (
    <div style={{ height: 500, overflow: 'auto' }}>
      <svg role="img" aria-label={`图谱：${graph.nodes.length} 个节点，${graph.edges.length} 条边`}
        viewBox={layout.bounds} style={{ width: '100%', height: '100%', minWidth: 600, background: '#fafafa' }}>
        {graph.directed && <defs>
          <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4"
            orient="auto" markerUnits="userSpaceOnUse">
            <path d="M0,0 L8,4 L0,8 Z" fill="#777" />
          </marker>
        </defs>}
        {layout.links.map((edge, index) => (
          <g key={index}>
            <line x1={edge.from.x} y1={edge.from.y}
              x2={graph.directed ? edge.to.x - 75 * (edge.to.x - edge.from.x) / (Math.hypot(edge.to.x - edge.from.x, edge.to.y - edge.from.y) || 1) : edge.to.x}
              y2={graph.directed ? edge.to.y - 75 * (edge.to.y - edge.from.y) / (Math.hypot(edge.to.x - edge.from.x, edge.to.y - edge.from.y) || 1) : edge.to.y}
              stroke="#777" strokeWidth={1.5} markerEnd={graph.directed ? 'url(#graph-arrow)' : undefined} />
            {edge.label && <text x={(edge.from.x + edge.to.x) / 2} y={(edge.from.y + edge.to.y) / 2 - 5}
              textAnchor="middle" fontSize={10} fill="#333">{edge.label.slice(0, 40)}</text>}
          </g>
        ))}
        {layout.nodes.map((node) => {
          const lines = node.label.split('\n').slice(0, 4).map((line) => line.slice(0, 25));
          const circle = node.shape === 'circle';
          return (
            <g key={node.id} transform={`translate(${node.x},${node.y})`}>
              <title>{node.label}</title>
              {circle ? <circle r={48} fill={node.fill} /> :
                <rect x={-70} y={-Math.max(24, lines.length * 9 + 8)} width={140}
                  height={Math.max(48, lines.length * 18 + 16)} rx={8} fill={node.fill} />}
              <text textAnchor="middle" fill={node.color} fontSize={12}>
                {lines.map((line, index) =>
                  <tspan key={index} x={0} y={(index - (lines.length - 1) / 2) * 16 + 4}>{line}</tspan>)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
