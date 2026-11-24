import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import SkyCameras from "./SkyCameras";
import { isAllowedPlayer } from "@/components/skywatcher/CameraCard";

const { list, coverage, submit, submissions, decide } = vi.hoisted(() => ({
  list: vi.fn(),
  coverage: vi.fn(),
  submit: vi.fn(),
  submissions: vi.fn(),
  decide: vi.fn(),
}));

vi.mock("@/api/federationClient", () => ({
  federation: { skyCameras: { list, coverage, submit, submissions, decide } },
}));

const SONESTA = {
  id: "carolina-isla-verde-royal-sonesta",
  name: "Isla Verde Beach — Royal Sonesta San Juan",
  categories: ["beach", "coast", "sky"],
  municipality: "Carolina",
  provider: "Ozolio",
  page_url: "https://www.ozolio.com/explore/EQXF000015F1",
  embed_url: "https://www.youtube-nocookie.com/embed/taI7GiyvDxE",
  media_url: null,
  status: "online",
  checked_at: "2026-11-07",
  added_by: "curated",
};
const CONDADO = {
  ...SONESTA,
  id: "san-juan-condado-lagoon-skyline",
  name: "Condado Lagoon",
  categories: ["lagoon", "coast", "sky"],
  municipality: "San Juan",
  provider: "SkylineWebcams",
  page_url: "https://www.skylinewebcams.com/en/webcam/puerto-rico/san-juan/san-juan/condado-lagoon.html",
  embed_url: null,
};
const PAYLOAD = { categories: [], municipios: ["Carolina", "San Juan"], count: 2, cameras: [SONESTA, CONDADO] };

beforeEach(() => {
  window.localStorage.clear();
  list.mockResolvedValue(PAYLOAD);
  coverage.mockResolvedValue({
    camera_count: 2,
    online_count: 2,
    municipio_total: 78,
    municipios_covered: 2,
    categories_without_cameras: ["river", "lake"],
  });
  submit.mockResolvedValue({ id: "abc", status: "pending", message: "Thanks! Your submission is in the review queue." });
  submissions.mockResolvedValue({ submissions: [] });
});
afterEach(() => vi.clearAllMocks());

describe("SkyCameras", () => {
  it("lists cameras, embeds only allowlisted players and shows coverage gaps", async () => {
    render(<SkyCameras />);
    const sonesta = await screen.findByRole("article", { name: SONESTA.name });
    expect(within(sonesta).getByTitle(`Live view: ${SONESTA.name}`).getAttribute("src")).toBe(SONESTA.embed_url);
    const condado = screen.getByRole("article", { name: "Condado Lagoon" });
    expect(within(condado).queryByTitle(/Live view/)).toBeNull();
    expect(within(condado).getByRole("link", { name: /Open live stream/ }).getAttribute("href")).toBe(CONDADO.page_url);
    expect(await screen.findByText(/2\/78/)).toBeTruthy();
    expect(screen.getByText(/No river, lake cameras yet/)).toBeTruthy();
  });

  it("switches every card to links only and remembers it", async () => {
    render(<SkyCameras />);
    await screen.findByRole("article", { name: SONESTA.name });
    fireEvent.click(screen.getByRole("button", { name: "Players on" }));
    expect(screen.queryByTitle(/Live view/)).toBeNull();
    expect(window.localStorage.getItem("skywatcher.skyCameras.showPlayers")).toBe("off");
  });

  it("filters by category", async () => {
    render(<SkyCameras />);
    await screen.findByRole("article", { name: SONESTA.name });
    fireEvent.click(within(screen.getByRole("group", { name: "Category" })).getByRole("button", { name: "Beach" }));
    await waitFor(() => expect(list).toHaveBeenLastCalledWith({ category: "beach", municipality: "", q: "" }));
  });

  it("requires the attestations before sending a suggestion for review", async () => {
    render(<SkyCameras />);
    await screen.findByRole("article", { name: SONESTA.name });
    fireEvent.click(screen.getByRole("button", { name: "Contribute" }));
    const form = screen.getByRole("form", { name: "Contribute" });
    fireEvent.change(within(form).getByLabelText("Title"), { target: { value: "Playa Jobos" } });
    fireEvent.change(within(form).getByLabelText(/Camera page link/), { target: { value: "https://example.org/jobos" } });
    fireEvent.click(within(form).getByLabelText("Beach"));
    fireEvent.click(within(form).getByRole("button", { name: "Send for review" }));
    expect((await within(form).findByRole("alert")).textContent).toMatch(/Confirm both statements/);
    expect(submit).not.toHaveBeenCalled();

    fireEvent.click(within(form).getByLabelText(/already shown to the public/));
    fireEvent.click(within(form).getByLabelText(/no identifiable people/));
    fireEvent.click(within(form).getByRole("button", { name: "Send for review" }));
    await within(form).findByRole("status");
    const body = submit.mock.calls[0][0];
    expect(body.get("kind")).toBe("camera_link");
    expect(body.get("url")).toBe("https://example.org/jobos");
    expect(body.getAll("categories")).toEqual(["beach"]);
    expect(body.get("attest_consent")).toBe("true");
  });

  it("explains when reviewing is not allowed", async () => {
    submissions.mockRejectedValue(Object.assign(new Error("Forbidden"), { status: 403 }));
    render(<SkyCameras />);
    await screen.findByRole("article", { name: SONESTA.name });
    fireEvent.click(screen.getByRole("button", { name: "Review queue" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/write access/);
  });
});

describe("isAllowedPlayer", () => {
  it("accepts only the youtube-nocookie and vimeo players", () => {
    expect(isAllowedPlayer("https://www.youtube-nocookie.com/embed/taI7GiyvDxE")).toBe(true);
    expect(isAllowedPlayer("https://player.vimeo.com/video/123456789")).toBe(true);
    expect(isAllowedPlayer("https://evil.example/embed/x")).toBe(false);
    expect(isAllowedPlayer("javascript:alert(1)")).toBe(false);
  });
});
