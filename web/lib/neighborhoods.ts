/**
 * NYC neighborhood → zip code mapping.
 * Mirrors NEIGHBORHOOD_ZIP_CODES in src/engines/real_estate.py.
 */

export const NEIGHBORHOOD_ZIP_CODES: Record<string, string[]> = {
  // Manhattan
  "Hudson Yards": ["10001", "10018"],
  SoHo: ["10012", "10013"],
  Tribeca: ["10007", "10013"],
  NoHo: ["10003", "10012"],
  "Central Park South": ["10019"],
  NoLIta: ["10012"],
  "Hudson Square": ["10013", "10014"],
  "Carnegie Hill": ["10128"],
  NoMad: ["10010", "10016"],
  "Central Midtown": ["10017", "10022", "10036"],
  "West Village": ["10014"],
  "Two Bridges": ["10002", "10038"],
  "Flatiron District": ["10010"],
  "Garment District": ["10018", "10036"],
  "Lenox Hill": ["10021", "10065", "10075"],
  "Lincoln Square": ["10023"],
  "Greenwich Village": ["10003", "10011", "10012"],
  "Theatre District": ["10019", "10036"],
  Chelsea: ["10001", "10011"],
  "Upper West Side": ["10023", "10024", "10025"],
  "Financial District": ["10004", "10005", "10006", "10038"],
  "East Village": ["10003", "10009"],
  "Gramercy Park": ["10003", "10010"],
  "Manhattan Valley": ["10025"],
  "Stuyvesant Town": ["10009", "10010"],
  "Lower East Side": ["10002"],
  // Brooklyn
  "Cobble Hill": ["11201", "11231"],
  DUMBO: ["11201"],
  "Boerum Hill": ["11201", "11217"],
  "Columbia St Waterfront": ["11231"],
  "Carroll Gardens": ["11231"],
  Williamsburg: ["11211", "11249"],
  "Greenwood Heights": ["11232"],
  "Park Slope": ["11215", "11217"],
  Greenpoint: ["11222"],
  Gowanus: ["11215", "11217"],
  "Fort Greene": ["11205", "11217"],
  "Red Hook": ["11231"],
  "Manhattan Beach": ["11235"],
  "Mill Basin": ["11234"],
  "Prospect Heights": ["11238"],
  "Brooklyn Heights": ["11201"],
  "Downtown Brooklyn": ["11201", "11217"],
  "Prospect-Lefferts Gdns": ["11225"],
  "Clinton Hill": ["11205", "11238"],
  // Queens
  Malba: ["11357"],
  "Fresh Meadows": ["11365", "11366"],
  "Belle Harbor": ["11694"],
  "Hunters Point": ["11101"],
  "Long Island City": ["11101", "11109"],
};

/** All unique zip codes across all neighborhoods */
export const ALL_ZIP_CODES = [
  ...new Set(Object.values(NEIGHBORHOOD_ZIP_CODES).flat()),
];

/** Reverse map: zip → neighborhood name */
export const ZIP_TO_NEIGHBORHOOD: Record<string, string> = {};
for (const [neighborhood, zips] of Object.entries(NEIGHBORHOOD_ZIP_CODES)) {
  for (const zip of zips) {
    ZIP_TO_NEIGHBORHOOD[zip] = neighborhood;
  }
}

/** Given a zip code, return the neighborhood name or "NYC" */
export function zipToNeighborhood(zip: string | null): string {
  if (!zip) return "NYC";
  return ZIP_TO_NEIGHBORHOOD[zip] ?? "NYC";
}
