import SwiftUI

struct SettingsView: View {
    @AppStorage("geminiAPIKey") private var geminiAPIKey = ""
    @AppStorage("dataDirectory") private var dataDirectory = ""
    @State private var showDirectoryPicker = false
    @State private var statusMessage = ""

    var body: some View {
        Form {
            Section("Data Directory") {
                HStack {
                    if dataDirectory.isEmpty {
                        Text("~/.kindle-brain/ (default)")
                            .foregroundStyle(.secondary)
                    } else {
                        Text(dataDirectory)
                            .lineLimit(1)
                            .truncationMode(.middle)
                    }
                    Spacer()
                    Button("Choose...") {
                        chooseDirectory()
                    }
                }
                Text("Point this to the folder containing kindle.db and books_md/")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if !statusMessage.isEmpty {
                    Label(statusMessage, systemImage: statusMessage.contains("Found") ? "checkmark.circle" : "exclamationmark.triangle")
                        .font(.caption)
                        .foregroundStyle(statusMessage.contains("Found") ? .green : .orange)
                }
            }

            Section("Gemini API Key") {
                SecureField("API Key", text: $geminiAPIKey)
                    .textFieldStyle(.roundedBorder)
                Text("Required for Chat and Explain Highlight features")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Link("Get a free key at aistudio.google.com",
                     destination: URL(string: "https://aistudio.google.com/")!)
                    .font(.caption)
            }

            Section("About") {
                LabeledContent("Version", value: "0.1.0")
                Link("GitHub Repository",
                     destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
                    .font(.callout)
            }
        }
        .formStyle(.grouped)
        .frame(width: 500, height: 350)
        .onAppear { validateDirectory() }
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
            validateDirectory()
        }
    }

    private func validateDirectory() {
        let dir = dataDirectory.isEmpty
            ? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".kindle-brain").path
            : dataDirectory

        let dbExists = FileManager.default.fileExists(atPath: "\(dir)/kindle.db")
        let mdExists = FileManager.default.fileExists(atPath: "\(dir)/books_md/CATALOG.md")

        if dbExists && mdExists {
            statusMessage = "Found kindle.db + CATALOG.md"
        } else if dbExists {
            statusMessage = "Found kindle.db (run kindle-brain generate --catalog for best results)"
        } else {
            statusMessage = "kindle.db not found — run kindle-brain setup first"
        }
    }
}
