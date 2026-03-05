/**
 * TypeScript types matching the PostgreSQL schema in Supabase.
 * Keep in sync with src/models/lead.py on the Python side.
 */

export type LeadSource =
  | "sec_edgar"
  | "tax_assessor"
  | "professional_mapping"
  | "fec_campaign_finance"
  | "manual";

export type OutreachStatus =
  | "pending"
  | "draft_ready"
  | "approved"
  | "sent"
  | "opened"
  | "replied"
  | "booked";

export interface Lead {
  id: number;
  first_name: string;
  last_name: string;
  name_key: string;
  city: string | null;
  state: string | null;
  zip_code: string | null;
  address: string | null;
  professional_title: string | null;
  company: string | null;
  linkedin_url: string | null;
  email: string | null;
  phone: string | null;
  email_reveal_attempted: number;
  phone_reveal_attempted: number;
  estimated_wealth: number | null;
  discovery_trigger: string;
  year_built: number | null;
  num_floors: number | null;
  building_area: number | null;
  lot_area: number | null;
  building_type: string | null;
  unit_number: string | null;
  deed_sale_amount: number | null;
  deed_date: string | null;
  source: LeadSource;
  confidence_score: number;
  discovered_at: string;
  outreach_status: OutreachStatus;
  outreach_draft: string | null;
  created_at: string;
  updated_at: string;
}

export interface StatsResponse {
  leadCount: number;
  lastSync: string | null;
}

export interface LeadsResponse {
  leads: Lead[];
  total: number;
}

export interface OutreachResponse {
  draft: string;
}
