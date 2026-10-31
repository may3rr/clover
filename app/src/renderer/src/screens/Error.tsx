export default function ErrorScreen() {
  return (
    <div
      className="h-full flex flex-col items-center justify-center gap-4"
      style={{ background: 'var(--bg)' }}
    >
      <div className="font-semibold">无法启动本地服务。</div>
      <div className="font-normal">
        请退出 Clover 后重新打开。如果仍然出现，请把日志发给开发者。
      </div>
    </div>
  )
}
