// Brand avatar for the 13 built-in specialists (web/public/specialists/<id>.png); a colored dot for any other id.
const AVATARS = new Set(["core", "code", "finance", "medicine", "law", "marketing", "science", "data", "math", "education",
  "writing", "business", "security"]);

export function SpecMark({ id }: { id: string }) {
  return AVATARS.has(id)
    ? <img className="chip-avatar" src={`/specialists/${id}.png`} alt="" width={18} height={18} />
    : <span className="chip-dot" />;
}
