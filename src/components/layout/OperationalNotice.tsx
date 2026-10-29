type OperationalNoticeProps = {
  tone: "info" | "warning" | "error";
  title: string;
  detail?: string;
};

export function OperationalNotice({ tone, title, detail }: OperationalNoticeProps) {
  return (
    <div
      className="operational-notice"
      data-tone={tone}
      role={tone === "info" ? "status" : "alert"}
    >
      <span className="operational-notice-mark" aria-hidden="true" />
      <div>
        <p className="operational-notice-title">{title}</p>
        {detail ? <p className="operational-notice-detail">{detail}</p> : null}
      </div>
    </div>
  );
}
