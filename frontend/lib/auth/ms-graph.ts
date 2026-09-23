import { graphConfig } from "./azure-ad-config";
import type { MSALGraphMeData } from "@/types/msgraph-me";

export async function callMsGraph(
  accessToken: string
): Promise<MSALGraphMeData> {
  const headers = new Headers();
  headers.append("Authorization", `Bearer ${accessToken}`);

  const response = await fetch(graphConfig.graphMeEndpoint, {
    method: "GET",
    headers,
  });

  if (!response.ok) {
    throw new Error(`Graph API error: ${response.status}`);
  }

  return response.json();
}
