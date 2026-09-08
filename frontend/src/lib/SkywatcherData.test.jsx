import React from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SkywatcherDataProvider, useSkywatcher } from "./SkywatcherData";

const api = vi.hoisted(() => ({ list: vi.fn(), update: vi.fn(), create: vi.fn() }));
vi.mock("@/api/federationClient", () => ({ federation: { entities: new Proxy({}, { get: () => api }) } }));
const wrapper = ({ children }) => <SkywatcherDataProvider>{children}</SkywatcherDataProvider>;
const record = { id: "obs-1", review_status: "open", notes: "Original" };
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

beforeEach(() => { vi.resetAllMocks(); api.list.mockResolvedValue([record]); });
describe("confirmed data state", () => {
  it("retains records and exposes failed reloads, then clears errors after recovery", async () => {
    const { result } = renderHook(useSkywatcher, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.list.mockRejectedValue(new Error("Offline"));
    await act(() => result.current.reload());
    expect(result.current.observations).toEqual([record]);
    expect(result.current.loadErrors.observations).toBe("Offline");
    api.list.mockResolvedValue([]);
    await act(() => result.current.reload());
    expect(result.current.observations).toEqual([]);
    expect(result.current.loadErrors).toEqual({});
  });
  it("rejects malformed collection responses instead of rendering them as records", async () => {
    api.list.mockResolvedValue({ error: "not an array" });
    const { result } = renderHook(useSkywatcher, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.observations).toEqual([]);
    expect(result.current.loadErrors.observations).toBe("Invalid collection response");
  });
  it("does not publish a rejected write and uses the server record on success", async () => {
    const { result } = renderHook(useSkywatcher, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    api.update.mockRejectedValue(new Error("Denied"));
    await act(async () => { await expect(result.current.updateRecord("observations", "obs-1", { review_status: "verified" })).rejects.toThrow("Denied"); });
    expect(result.current.observations).toEqual([record]);
    const accepted = { ...record, review_status: "triaged", notes: "Server value" };
    api.update.mockResolvedValue(accepted);
    await act(() => result.current.updateRecord("observations", "obs-1", { review_status: "verified" }));
    expect(result.current.observations).toEqual([accepted]);
  });
  it("ignores an older reload that completes after the newest reload", async () => {
    const { result } = renderHook(useSkywatcher, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const old = deferred(); api.list.mockReturnValue(old.promise);
    let first; act(() => { first = result.current.reload(); });
    api.list.mockResolvedValue([{ id: "new" }]);
    await act(() => result.current.reload());
    await act(async () => { old.resolve([record]); await first; });
    expect(result.current.observations).toEqual([{ id: "new" }]);
  });
  it("does not overwrite a confirmed edit with an in-flight read", async () => {
    const { result } = renderHook(useSkywatcher, { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const old = deferred(); api.list.mockReturnValue(old.promise);
    let pending; act(() => { pending = result.current.reload(); });
    const accepted = { ...record, review_status: "verified" }; api.update.mockResolvedValue(accepted);
    await act(() => result.current.updateRecord("observations", record.id, accepted));
    await act(async () => { old.resolve([record]); await pending; });
    expect(result.current.observations).toEqual([accepted]);
  });
});
