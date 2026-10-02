export default function ErrorScreen() {
  return (
    <div
      className="h-full flex flex-col items-center justify-center gap-4"
      style={{ background: 'var(--bg)' }}
    >
      <div className="font-semibold">无法启动本地服务。</div>
      <div className="font-normal">
        请确认 Python 环境可用，然后重新打开应用。
      </div>
    </div>
  )
}
