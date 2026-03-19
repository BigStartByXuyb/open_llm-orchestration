import { describe, it, expect } from "vitest";
import { t } from "../i18n";

describe("i18n", () => {
  it("returns zh translation", () => {
    expect(t("app.name", "zh")).toBe("Canopy Orchestr");
    expect(t("nav.home", "zh")).toBe("对话");
  });

  it("returns en translation", () => {
    expect(t("app.name", "en")).toBe("Canopy Orchestr");
    expect(t("nav.home", "en")).toBe("Chat");
  });

  it("falls back to zh for unknown lang", () => {
    expect(t("nav.home", "fr")).toBe("对话");
  });

  it("returns the key itself for unknown key", () => {
    expect(t("nonexistent.key", "zh")).toBe("nonexistent.key");
  });
});
