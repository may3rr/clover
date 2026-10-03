Clover for macOS (Apple Silicon).

**First launch.** The app is not notarized. If macOS says it cannot verify the developer, open System Settings > Privacy & Security and click **Open Anyway**. You can also run `xattr -cr /Applications/Clover.app` once.

**Setup.** Enter an Alibaba Cloud Bailian (DashScope) API key in onboarding or in Settings > 模型. The key is stored in `~/Library/Application Support/Clover/.env` and nowhere else.

Only English papers (.docx) are supported for now.
