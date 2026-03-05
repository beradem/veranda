"use client";

/**
 * Hero — Welcome screen shown before the first search is performed.
 * Centered luxury branding with instructions.
 */

export function Hero() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-8">
      {/* Wordmark */}
      <div className="mb-6">
        <h1
          className="text-6xl font-normal tracking-[0.15em] uppercase"
          style={{
            fontFamily: "'Playfair Display', Georgia, serif",
            color: "#EDE8E0",
          }}
        >
          Veranda
        </h1>
        <div className="gold-rule my-4 w-48 mx-auto" />
        <p
          className="text-xs tracking-[0.3em] uppercase"
          style={{ color: "#7A7570" }}
        >
          NYC Intelligence Platform
        </p>
      </div>

      {/* Instruction cards */}
      <div className="mt-12 grid grid-cols-3 gap-6 max-w-2xl w-full">
        {[
          {
            step: "01",
            label: "Describe Your Service",
            desc: "Enter your business pitch in the sidebar to personalize outreach.",
          },
          {
            step: "02",
            label: "Select Neighborhoods",
            desc: "Choose the NYC neighborhoods that match your target market.",
          },
          {
            step: "03",
            label: "Engage Leads",
            desc: "Click any lead to review their wealth signals and generate outreach.",
          },
        ].map(({ step, label, desc }) => (
          <div
            key={step}
            className="p-5 rounded border text-left"
            style={{
              backgroundColor: "#111115",
              borderColor: "#252530",
            }}
          >
            <div
              className="text-xs font-semibold tracking-[0.2em] mb-3"
              style={{ color: "#C8A96E" }}
            >
              {step}
            </div>
            <div
              className="text-sm font-medium mb-2"
              style={{
                fontFamily: "'Playfair Display', Georgia, serif",
                color: "#EDE8E0",
              }}
            >
              {label}
            </div>
            <div className="text-xs leading-relaxed" style={{ color: "#7A7570" }}>
              {desc}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
