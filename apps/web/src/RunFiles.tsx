import { Paperclip, X } from "lucide-react";

const MIB = 1024 * 1024;
export async function encodeFiles(files: File[]) {
  return Promise.all(
    files.map(async (file) => {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192) {
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      }
      return { name: file.name, content_base64: btoa(binary) };
    }),
  );
}

export function RunFiles({
  files,
  onChange,
  disabled,
  onError,
}: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled: boolean;
  onError: (message: string) => void;
}) {
  function add(selected: FileList | null) {
    const next = [...files, ...Array.from(selected || [])];
    if (
      next.length > 8 ||
      next.some((f) => f.size > MIB) ||
      next.reduce((n, f) => n + f.size, 0) > 4 * MIB
    ) {
      onError("Attach up to 8 files, at most 1 MiB each and 4 MiB total.");
      return;
    }
    if (new Set(next.map((f) => f.name)).size !== next.length) {
      onError(
        "File names must be unique. Remove the existing file before replacing it.",
      );
      return;
    }
    if (
      next.some(
        (f) =>
          !/^[a-zA-Z0-9_][a-zA-Z0-9_. -]{0,149}$/.test(f.name) ||
          f.name.endsWith(" "),
      )
    ) {
      onError(
        "Rename files using letters, numbers, spaces, underscores, dots, or hyphens; start with a letter, number, or underscore.",
      );
      return;
    }
    onError("");
    onChange(next);
  }
  return (
    <div className="run-files">
      <label htmlFor="run-files">
        <Paperclip size={15} /> Attach files
      </label>
      <input
        id="run-files"
        type="file"
        multiple
        disabled={disabled}
        aria-describedby="file-limits"
        onChange={(e) => {
          add(e.target.files);
          e.target.value = "";
        }}
      />
      <p id="file-limits" className="hint">
        Up to 8 files · 1 MiB each · 4 MiB total. Temporary for this run;
        available under <code>inputs/</code>.
      </p>
      {files.some((file) => /\.(zip|tar|tar\.gz|tgz)$/i.test(file.name)) && (
        <p className="hint">
          The archive tool will be added automatically and extract these uploads
          for this run.
        </p>
      )}
      {files.map((file) => (
        <div className="attachment-row" key={file.name}>
          <span>
            {file.name} <small>{file.size.toLocaleString()} bytes</small>
          </span>
          <button
            className="text-button"
            disabled={disabled}
            aria-label={`Remove ${file.name}`}
            onClick={() => onChange(files.filter((f) => f !== file))}
          >
            <X size={15} />
          </button>
        </div>
      ))}
    </div>
  );
}
