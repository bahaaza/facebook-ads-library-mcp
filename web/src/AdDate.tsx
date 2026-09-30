import "./AdDate.css";

const months = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

function advertisedDate(value: unknown): Date | null {
  if (typeof value !== "string") return null;
  const text = value.trim();
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(text);
  const english = /^([a-z]+)\s+(\d{1,2}),\s*(\d{4})$/i.exec(text);
  let year: number, month: number, day: number;
  if (iso) {
    year = Number(iso[1]);
    month = Number(iso[2]);
    day = Number(iso[3]);
  } else if (english) {
    year = Number(english[3]);
    day = Number(english[2]);
    const name = english[1].toLowerCase();
    month =
      months.findIndex(
        (candidate) =>
          candidate.toLowerCase() === name ||
          candidate.slice(0, 3).toLowerCase() === name ||
          (candidate === "September" && name === "sept"),
      ) + 1;
  } else {
    return null;
  }

  // Avoid permissive Date parsing, which rolls impossible dates into another month.
  const result = new Date(0);
  result.setUTCFullYear(year, month - 1, day);
  if (
    year < 1 ||
    result.getUTCFullYear() !== year ||
    result.getUTCMonth() !== month - 1 ||
    result.getUTCDate() !== day
  ) {
    return null;
  }
  return result;
}

export function AdDate({
  value,
  className = "",
}: {
  value: unknown;
  className?: string;
}) {
  const parsed = advertisedDate(value);
  return (
    <div
      className={`ad-date ${className}`.trim()}
      title="Date Meta reports this ad started running."
    >
      {parsed ? (
        <>
          <div className="ad-date__label">Advertised since</div>
          <strong>
            <time dateTime={parsed.toISOString().slice(0, 10)}>
              {parsed.toLocaleDateString(undefined, {
                year: "numeric",
                month: "short",
                day: "numeric",
                timeZone: "UTC",
              })}
            </time>
          </strong>
        </>
      ) : (
        <div className="ad-date__unavailable">Advertised date unavailable</div>
      )}
    </div>
  );
}
