"use client";

import { useCallback, useMemo, useState } from "react";
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  MarkerType,
  Panel,
} from "reactflow";
import "reactflow/dist/style.css";
import { Hash, Type, Calendar, List, Braces, ToggleLeft } from "lucide-react";
import { PlusIcon } from "@/components/ui/plus";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

interface VisualSchemaEditorProps {
  schema: Record<string, unknown>;
  onChange: (schema: Record<string, unknown>) => void;
  readOnly?: boolean;
}

// Custom node component
function FieldNode({ data }: { data: { label: string; type: string; required: boolean } }) {
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "string":
        return <Type className="h-3 w-3" />;
      case "number":
      case "integer":
        return <Hash className="h-3 w-3" />;
      case "boolean":
        return <ToggleLeft className="h-3 w-3" />;
      case "array":
        return <List className="h-3 w-3" />;
      case "object":
        return <Braces className="h-3 w-3" />;
      default:
        return <Type className="h-3 w-3" />;
    }
  };

  const getTypeColor = (type: string) => {
    switch (type) {
      case "string":
        return "border-green-500 bg-green-50 dark:bg-green-950/20";
      case "number":
      case "integer":
        return "border-blue-500 bg-blue-50 dark:bg-blue-950/20";
      case "boolean":
        return "border-purple-500 bg-purple-50 dark:bg-purple-950/20";
      case "array":
        return "border-orange-500 bg-orange-50 dark:bg-orange-950/20";
      case "object":
        return "border-cyan-500 bg-cyan-50 dark:bg-cyan-950/20";
      default:
        return "border-gray-500 bg-gray-50 dark:bg-gray-950/20";
    }
  };

  return (
    <div
      className={cn(
        "px-4 py-2 rounded-lg border-2 shadow-sm min-w-[150px]",
        getTypeColor(data.type)
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {getTypeIcon(data.type)}
          <span className="font-medium text-sm">{data.label}</span>
        </div>
        {data.required && (
          <Badge variant="destructive" className="text-xs px-1">
            *
          </Badge>
        )}
      </div>
      <div className="text-xs text-muted-foreground mt-1">{data.type}</div>
    </div>
  );
}

const nodeTypes = {
  field: FieldNode,
};

export function VisualSchemaEditor({
  schema,
  onChange,
  readOnly = false,
}: VisualSchemaEditorProps) {
  // Convert schema to nodes and edges
  const { initialNodes, initialEdges } = useMemo(() => {
    const nodes: Node[] = [];
    const edges: Edge[] = [];

    const properties = schema.properties as Record<string, unknown> | undefined;
    const required = (schema.required as string[]) || [];

    if (!properties) {
      return { initialNodes: [], initialEdges: [] };
    }

    let y = 0;
    const processProperty = (
      key: string,
      prop: Record<string, unknown>,
      parentId: string | null,
      level: number
    ) => {
      const nodeId = parentId ? `${parentId}.${key}` : key;
      const type = (prop.type as string) || "string";

      nodes.push({
        id: nodeId,
        type: "field",
        position: { x: level * 250, y },
        data: {
          label: key,
          type,
          required: required.includes(key),
        },
      });

      if (parentId) {
        edges.push({
          id: `${parentId}-${nodeId}`,
          source: parentId,
          target: nodeId,
          markerEnd: { type: MarkerType.ArrowClosed },
          style: { strokeWidth: 2 },
        });
      }

      y += 80;

      // Handle nested objects
      if (type === "object" && prop.properties) {
        const nestedProps = prop.properties as Record<string, unknown>;
        Object.entries(nestedProps).forEach(([nestedKey, nestedProp]) => {
          processProperty(nestedKey, nestedProp as Record<string, unknown>, nodeId, level + 1);
        });
      }

      // Handle arrays of objects
      if (type === "array" && prop.items) {
        const items = prop.items as Record<string, unknown>;
        if (items.type === "object" && items.properties) {
          const nestedProps = items.properties as Record<string, unknown>;
          Object.entries(nestedProps).forEach(([nestedKey, nestedProp]) => {
            processProperty(nestedKey, nestedProp as Record<string, unknown>, nodeId, level + 1);
          });
        }
      }
    };

    Object.entries(properties).forEach(([key, prop]) => {
      processProperty(key, prop as Record<string, unknown>, null, 0);
    });

    return { initialNodes: nodes, initialEdges: edges };
  }, [schema]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges]
  );

  const addField = (type: string) => {
    const fieldName = `new_field_${Date.now()}`;
    const newNode: Node = {
      id: fieldName,
      type: "field",
      position: { x: 100, y: nodes.length * 80 },
      data: {
        label: fieldName,
        type,
        required: false,
      },
    };
    setNodes((nds) => [...nds, newNode]);

    // Update schema
    const newSchema = { ...schema };
    if (!newSchema.properties) {
      newSchema.properties = {};
    }
    (newSchema.properties as Record<string, unknown>)[fieldName] = { type };
    onChange(newSchema);
  };

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={!readOnly}
      >
        <Background />
        <Controls />
        {!readOnly && (
          <Panel position="top-left">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm">
                  <PlusIcon size={16} className="mr-2" />
                  Add Field
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onClick={() => addField("string")}>
                  <Type className="h-4 w-4 mr-2" />
                  String
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addField("number")}>
                  <Hash className="h-4 w-4 mr-2" />
                  Number
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addField("boolean")}>
                  <ToggleLeft className="h-4 w-4 mr-2" />
                  Boolean
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addField("array")}>
                  <List className="h-4 w-4 mr-2" />
                  Array
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => addField("object")}>
                  <Braces className="h-4 w-4 mr-2" />
                  Object
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}
