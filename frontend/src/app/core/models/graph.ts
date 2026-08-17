export type GraphMode = 'mixed' | 'schema' | 'instance';
export type GraphNodeType = 'class' | 'obj_prop' | 'data_prop' | 'instance';
export type GraphLinkType = 'schema_link' | 'instance_of' | 'instance_rel';

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  dp?: number | null;
  op?: number | null;
  inst?: number | null;
  classId?: string | null;
}

export interface GraphLink {
  source: string;
  target: string;
  type: GraphLinkType;
  label?: string | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  links: GraphLink[];
}

export interface GraphNodeDetail {
  id: string;
  type: GraphNodeType;
  label: string;
  fields: { key: string; value: string }[];
}
