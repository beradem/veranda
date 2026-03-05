/**
 * POST /api/leads/[nameKey]/outreach
 *
 * Generates a personalized outreach message via Groq (Llama 3.3 70B),
 * saves the draft to Supabase, and returns the generated text.
 *
 * Body: { serviceDescription: string, lead: Lead }
 * Returns: { draft: string }
 */

import { NextRequest, NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import type { Lead, OutreachResponse } from "@/lib/types";

const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";
const GROQ_MODEL = "llama-3.3-70b-versatile";

function getEraDescription(year: number | null): string {
  if (!year) return "unknown era";
  if (year < 1900) return "historic";
  if (year < 1940) return "pre-war";
  if (year < 1960) return "mid-century";
  if (year < 1980) return "post-war";
  if (year < 2000) return "contemporary";
  return "modern";
}

function buildPrompt(lead: Lead, serviceDescription: string): string {
  const details: string[] = [];

  if (lead.estimated_wealth) {
    const val =
      lead.estimated_wealth >= 1_000_000
        ? `$${(lead.estimated_wealth / 1_000_000).toFixed(1)}M`
        : `$${lead.estimated_wealth.toLocaleString()}`;
    details.push(`Estimated value: ${val}`);
  }
  if (lead.building_type) details.push(`Property type: ${lead.building_type}`);
  if (lead.year_built) {
    details.push(`Built: ${lead.year_built} (${getEraDescription(lead.year_built)})`);
  }
  if (lead.building_area) details.push(`Building size: ${lead.building_area.toLocaleString()} sq ft`);
  if (lead.lot_area) details.push(`Lot size: ${lead.lot_area.toLocaleString()} sq ft`);
  if (lead.num_floors) details.push(`Floors: ${lead.num_floors}`);
  if (lead.address) details.push(`Address: ${lead.address}`);

  const propertyBlock =
    details.length > 0
      ? details.map((d) => `- ${d}`).join("\n")
      : "- No detailed property data available";

  const ownerName = `${lead.first_name} ${lead.last_name}`.trim() || "the owner";
  const firstName = lead.first_name.trim() || "there";

  // For SEC/professional leads, swap property context for professional context
  const contextBlock =
    lead.source === "sec_edgar"
      ? `PROFESSIONAL CONTEXT:\n- Company: ${lead.company ?? "—"}\n- Title: ${lead.professional_title ?? "—"}\n- Trigger: ${lead.discovery_trigger}`
      : `PROPERTY DETAILS:\n${propertyBlock}`;

  return `Write a short, personalized outreach message from a luxury service provider.

RECIPIENT: ${ownerName}
${contextBlock}

SERVICE PROVIDER DESCRIPTION:
${serviceDescription}

FORMAT — follow this exact structure:
1. "Hi ${firstName}," — then introduce who you are and reference one specific detail about them
2. One sentence connecting your services to their situation, ending with a soft, low-pressure close

RULES:
- EXACTLY 2 sentences total (after "Hi ${firstName},"). No more.
- Tone: direct, warm, confident — like a friendly neighbor who happens to be an expert
- Reference at least ONE specific detail (year, type, address, size, neighborhood, or company)
- Do NOT use clichés like "I noticed", "I came across", or "I couldn't help but"
- Do NOT use "Dear", "To whom it may concern", or formal greetings
- Do NOT add a subject line or sign-off
- Write ONLY the message body, starting with "Hi ${firstName},"`;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ nameKey: string }> }
) {
  try {
    const { nameKey } = await params;
    const body = await request.json();
    const { serviceDescription, lead } = body as {
      serviceDescription: string;
      lead: Lead;
    };

    if (!serviceDescription?.trim()) {
      return NextResponse.json(
        { error: "serviceDescription is required" },
        { status: 400 }
      );
    }

    const groqKey = process.env.GROQ_API_KEY;
    if (!groqKey) {
      return NextResponse.json(
        { error: "GROQ_API_KEY is not configured" },
        { status: 503 }
      );
    }

    const prompt = buildPrompt(lead, serviceDescription);

    const groqResponse = await fetch(GROQ_API_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${groqKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        model: GROQ_MODEL,
        messages: [{ role: "user", content: prompt }],
        max_tokens: 300,
        temperature: 0.7,
      }),
    });

    if (!groqResponse.ok) {
      const errText = await groqResponse.text();
      console.error("[/api/leads/outreach] Groq error:", errText);
      return NextResponse.json(
        { error: "Groq API request failed" },
        { status: 502 }
      );
    }

    const groqData = await groqResponse.json();
    const draft = groqData.choices?.[0]?.message?.content?.trim() ?? "";

    if (!draft) {
      return NextResponse.json(
        { error: "Groq returned an empty response" },
        { status: 502 }
      );
    }

    // Persist draft to Supabase
    const { error: updateError } = await supabase
      .from("leads")
      .update({
        outreach_draft: draft,
        outreach_status: "draft_ready",
        updated_at: new Date().toISOString(),
      })
      .eq("name_key", nameKey);

    if (updateError) {
      console.error("[/api/leads/outreach] Supabase update error:", updateError);
      // Return the draft anyway — outreach is still useful even if save failed
    }

    const response: OutreachResponse = { draft };
    return NextResponse.json(response);
  } catch (error) {
    console.error("[/api/leads/outreach]", error);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}
