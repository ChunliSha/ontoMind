import {
  AfterViewInit,
  Component,
  ElementRef,
  EventEmitter,
  Input,
  OnChanges,
  OnDestroy,
  Output,
  SimpleChanges,
  ViewChild,
} from '@angular/core';
import * as d3 from 'd3';
import { GraphLink, GraphNode } from '../../core/models/graph';

type SimNode = GraphNode & d3.SimulationNodeDatum;
type SimLink = d3.SimulationLinkDatum<SimNode> & GraphLink;

@Component({
  selector: 'app-d3-force-graph',
  standalone: true,
  template: `<svg #svgEl class="d3-graph-svg"></svg>`,
  styles: [`
    :host { display:block; width:100%; height:100%; }
    .d3-graph-svg { width:100%; height:100%; background:linear-gradient(180deg,#FBFBFE,#F4F5FA); border-radius:12px; }
  `],
})
export class D3ForceGraphComponent implements AfterViewInit, OnChanges, OnDestroy {
  @ViewChild('svgEl', { static: true }) svgRef!: ElementRef<SVGSVGElement>;
  @Input() nodes: GraphNode[] = [];
  @Input() links: GraphLink[] = [];
  @Input() search = '';
  @Output() nodeClick = new EventEmitter<GraphNode>();

  private sim: d3.Simulation<SimNode, SimLink> | null = null;
  private zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null;
  private svgSel: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null;
  private container: d3.Selection<SVGGElement, unknown, null, undefined> | null = null;
  private ready = false;

  ngAfterViewInit(): void {
    this.ready = true;
    this.render();
  }

  ngOnChanges(changes: SimpleChanges): void {
    if (!this.ready) return;
    if (changes['nodes'] || changes['links'] || changes['search']) this.render();
  }

  ngOnDestroy(): void {
    this.sim?.stop();
  }

  zoomBy(factor: number): void {
    if (!this.svgSel || !this.zoomBehavior) return;
    this.svgSel.transition().duration(200).call(this.zoomBehavior.scaleBy, factor);
  }

  resetZoom(): void {
    if (!this.svgSel || !this.zoomBehavior) return;
    this.svgSel.transition().duration(250).call(this.zoomBehavior.transform, d3.zoomIdentity);
  }

  private render(): void {
    const svgEl = this.svgRef.nativeElement;
    const width = svgEl.clientWidth || 760;
    const height = svgEl.clientHeight || 480;
    const q = this.search.trim().toLowerCase();

    let nodes = this.nodes.map((d) => ({ ...d }));
    let links = this.links.map((d) => ({ ...d }));
    if (q) {
      const hit = new Set(nodes.filter((n) => n.label.toLowerCase().includes(q)).map((n) => n.id));
      nodes = nodes.filter((n) => hit.has(n.id));
      links = links.filter((l) => hit.has(String(l.source)) && hit.has(String(l.target)));
    }

    const simNodes: SimNode[] = nodes.map((d) => ({ ...d }));
    const idMap = new Map(simNodes.map((n) => [n.id, n]));
    const simLinks: SimLink[] = links
      .map((d) => ({
        ...d,
        source: idMap.get(String(d.source)) ?? String(d.source),
        target: idMap.get(String(d.target)) ?? String(d.target),
      }))
      .filter((d) => typeof d.source !== 'string' && typeof d.target !== 'string') as SimLink[];

    this.sim?.stop();
    d3.select(svgEl).selectAll('*').remove();

    const svg = d3.select(svgEl).attr('viewBox', `0 0 ${width} ${height}`);
    this.svgSel = svg;
    const container = svg.append('g');
    this.container = container;

    this.zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => container.attr('transform', event.transform));
    svg.call(this.zoomBehavior);

    this.sim = d3.forceSimulation(simNodes)
      .force('link', d3.forceLink<SimNode, SimLink>(simLinks).id((d) => d.id).distance((d) => {
        if (d.type === 'schema_link') return 60;
        if (d.type === 'instance_of') return 50;
        return 120;
      }))
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide<SimNode>().radius((d) => {
        if (d.type === 'class') return 40;
        if (d.type === 'obj_prop') return 30;
        if (d.type === 'data_prop') return 25;
        return 20;
      }));

    const link = container.append('g').selectAll('line').data(simLinks).join('line')
      .attr('stroke', (d) => {
        if (d.type === 'instance_of') return '#C9C4F5';
        if (d.type === 'schema_link') return '#CBD5E1';
        return '#0C8F8A';
      })
      .attr('stroke-width', (d) => (d.type === 'schema_link' ? 1.5 : d.type === 'instance_of' ? 1.2 : 1.6))
      .attr('stroke-dasharray', (d) => (d.type === 'instance_of' ? '3 3' : 'none'))
      .attr('opacity', 0.85);

    const linkText = container.append('g').selectAll('text')
      .data(simLinks.filter((d) => !!d.label))
      .join('text')
      .attr('font-family', 'IBM Plex Mono')
      .attr('font-size', 10)
      .attr('fill', '#0C8F8A')
      .attr('text-anchor', 'middle')
      .text((d) => d.label || '');

    const node = container.append('g').selectAll<SVGGElement, SimNode>('g').data(simNodes).join('g')
      .style('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) this.sim?.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) this.sim?.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }) as unknown as (selection: d3.Selection<SVGGElement, SimNode, SVGGElement, unknown>) => void,
      )
      .on('click', (_event, d) => this.nodeClick.emit(d));

    node.append('circle')
      .attr('r', (d) => {
        if (d.type === 'class') return 26;
        if (d.type === 'obj_prop') return 20;
        if (d.type === 'data_prop') return 16;
        return 13;
      })
      .attr('fill', (d) => {
        if (d.type === 'class') return '#FBF0DC';
        if (d.type === 'obj_prop') return '#E0F5F4';
        if (d.type === 'data_prop') return '#EBF3FC';
        return '#ECE8FC';
      })
      .attr('stroke', (d) => {
        if (d.type === 'class') return '#C97A1E';
        if (d.type === 'obj_prop') return '#0C8F8A';
        if (d.type === 'data_prop') return '#3A76D2';
        return '#6E5CE0';
      })
      .attr('stroke-width', (d) => (d.type === 'class' ? 2 : 1.8));

    node.append('text')
      .attr('y', (d) => (d.type === 'class' ? 4 : 3))
      .attr('text-anchor', 'middle')
      .attr('font-family', (d) => (['class', 'obj_prop', 'data_prop'].includes(d.type) ? 'Inter' : 'IBM Plex Mono'))
      .attr('font-weight', (d) => (['class', 'obj_prop'].includes(d.type) ? 700 : 500))
      .attr('font-size', (d) => {
        if (d.type === 'class') return 12;
        if (d.type === 'obj_prop') return 10.5;
        if (d.type === 'data_prop') return 9.5;
        return 8;
      })
      .attr('fill', (d) => {
        if (d.type === 'class') return '#8A5A15';
        if (d.type === 'obj_prop') return '#096B67';
        if (d.type === 'data_prop') return '#295BAC';
        return '#5545C4';
      })
      .text((d) => d.label);

    this.sim.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimNode).x || 0)
        .attr('y1', (d) => (d.source as SimNode).y || 0)
        .attr('x2', (d) => (d.target as SimNode).x || 0)
        .attr('y2', (d) => (d.target as SimNode).y || 0);
      linkText
        .attr('x', (d) => (((d.source as SimNode).x || 0) + ((d.target as SimNode).x || 0)) / 2)
        .attr('y', (d) => (((d.source as SimNode).y || 0) + ((d.target as SimNode).y || 0)) / 2 - 5);
      node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });
  }
}
