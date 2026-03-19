import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskInput } from "../components/TaskInput";

// Mock the i18n hook
vi.mock("../hooks/useT", () => ({
  useT: () => (key: string) => key,
}));

describe("TaskInput", () => {
  it("renders textarea and send button", () => {
    render(<TaskInput onSubmit={vi.fn()} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("send button is disabled when textarea is empty", () => {
    render(<TaskInput onSubmit={vi.fn()} />);
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("send button is enabled when textarea has text", async () => {
    render(<TaskInput onSubmit={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox"), "Hello");
    expect(screen.getByRole("button")).not.toBeDisabled();
  });

  it("calls onSubmit with trimmed message on button click", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<TaskInput onSubmit={onSubmit} />);
    await userEvent.type(screen.getByRole("textbox"), "  test message  ");
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("test message"));
  });

  it("calls onSubmit when Enter is pressed (without Shift)", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<TaskInput onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "send this");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: false });
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("send this"));
  });

  it("does NOT submit on Shift+Enter", async () => {
    const onSubmit = vi.fn();
    render(<TaskInput onSubmit={onSubmit} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "multiline");
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables everything when disabled=true", () => {
    render(<TaskInput onSubmit={vi.fn()} disabled />);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
