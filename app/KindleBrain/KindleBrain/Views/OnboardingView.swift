import SwiftUI

struct OnboardingView: View {
    @AppStorage("dataDirectory") private var dataDirectory = ""
    @AppStorage("geminiAPIKey") private var geminiAPIKey = ""
    @AppStorage("onboardingComplete") private var onboardingComplete = false
    @State private var step = 0
    @State private var detectedPath = ""
    @State private var validationMessage = ""
    @State private var isValid = false

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(spacing: 16) {
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 48))
                    .foregroundStyle(Color.accentColor)
                Text("Welcome to Kindle Brain")
                    .font(.largeTitle.bold())
                Text("Let's set up your personal reading library")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
            .padding(.top, 48)
            .padding(.bottom, 32)

            // Step indicator
            HStack(spacing: 8) {
                ForEach(0..<2) { i in
                    Capsule()
                        .fill(i <= step ? Color.accentColor : Color.secondary.opacity(0.2))
                        .frame(width: i == step ? 32 : 12, height: 6)
                        .animation(.spring(duration: 0.3), value: step)
                }
            }
            .padding(.bottom, 32)

            // Step content
            Group {
                if step == 0 {
                    dataDirectoryStep
                } else {
                    apiKeyStep
                }
            }
            .frame(maxWidth: 480)
            .padding(.horizontal, 40)

            Spacer()

            // Navigation buttons
            HStack {
                if step > 0 {
                    Button("Back") { step -= 1 }
                        .keyboardShortcut(.cancelAction)
                }
                Spacer()
                if step == 0 {
                    Button("Next") { step = 1 }
                        .keyboardShortcut(.defaultAction)
                        .disabled(!isValid)
                } else {
                    Button("Get Started") {
                        onboardingComplete = true
                    }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                }
            }
            .padding(32)
        }
        .frame(width: 600, height: 520)
        .onAppear { autoDetectDataDir() }
    }

    // MARK: - Step 1: Data Directory

    private var dataDirectoryStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            Label("Data Directory", systemImage: "folder")
                .font(.headline)

            Text("Kindle Brain needs to know where your library data is stored. This folder should contain **kindle.db** and a **books_md/** folder.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineSpacing(2)

            // Auto-detected or chosen path
            HStack {
                Image(systemName: isValid ? "checkmark.circle.fill" : "folder")
                    .foregroundStyle(isValid ? .green : .secondary)
                if dataDirectory.isEmpty {
                    Text("No directory selected")
                        .foregroundStyle(.secondary)
                } else {
                    Text(dataDirectory)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }
                Spacer()
                Button("Choose...") { chooseDirectory() }
            }
            .padding(12)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 10))

            if !validationMessage.isEmpty {
                Label(validationMessage, systemImage: isValid ? "checkmark.circle" : "exclamationmark.triangle")
                    .font(.caption)
                    .foregroundStyle(isValid ? .green : .orange)
            }

            if !isValid {
                Text("Run `kindle-brain setup` in Terminal first to create your library data.")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
    }

    // MARK: - Step 2: API Key

    private var apiKeyStep: some View {
        VStack(alignment: .leading, spacing: 20) {
            Label("Gemini API Key", systemImage: "key")
                .font(.headline)

            Text("An API key is needed for the **Chat** and **Explain Highlight** features. You can get a free key from Google AI Studio.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineSpacing(2)

            SecureField("Paste your API key here", text: $geminiAPIKey)
                .textFieldStyle(.roundedBorder)
                .font(.body.monospaced())

            Link(destination: URL(string: "https://aistudio.google.com/")!) {
                Label("Get a free API key at aistudio.google.com", systemImage: "arrow.up.right")
                    .font(.callout)
            }

            Text("You can skip this step and add it later in Settings.")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
    }

    // MARK: - Helpers

    private func autoDetectDataDir() {
        // Try common locations
        let candidates = [
            FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".kindle-brain").path,
        ]

        // Also check env var
        if let env = ProcessInfo.processInfo.environment["KINDLE_BRAIN_DATA"] {
            let path = env
            if FileManager.default.fileExists(atPath: "\(path)/kindle.db") {
                dataDirectory = path
                validate(path)
                return
            }
        }

        for path in candidates {
            if FileManager.default.fileExists(atPath: "\(path)/kindle.db") {
                dataDirectory = path
                validate(path)
                return
            }
        }
    }

    private func chooseDirectory() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select your Kindle Brain data directory (contains kindle.db)"
        panel.prompt = "Select"

        if panel.runModal() == .OK, let url = panel.url {
            dataDirectory = url.path
            validate(url.path)
        }
    }

    private func validate(_ path: String) {
        let dbExists = FileManager.default.fileExists(atPath: "\(path)/kindle.db")
        let mdExists = FileManager.default.fileExists(atPath: "\(path)/books_md")

        if dbExists && mdExists {
            validationMessage = "Library found — kindle.db + books_md/"
            isValid = true
        } else if dbExists {
            validationMessage = "Found kindle.db (books_md/ not found — run kindle-brain generate)"
            isValid = true
        } else {
            validationMessage = "kindle.db not found at this location"
            isValid = false
        }
    }
}
