import SwiftUI

// MARK: - Focused Values for menu → view communication

struct SelectedTabKey: FocusedValueKey {
    typealias Value = Binding<ContentView.Tab>
}

extension FocusedValues {
    var selectedTab: Binding<ContentView.Tab>? {
        get { self[SelectedTabKey.self] }
        set { self[SelectedTabKey.self] = newValue }
    }
}

// MARK: - App

@main
struct KindleBrainApp: App {
    @StateObject private var chatVM = ChatViewModel()
    @StateObject private var libraryVM = LibraryViewModel()
    @StateObject private var memoryVM = MemoryViewModel()

    @FocusedBinding(\.selectedTab) private var selectedTab

    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 600, minHeight: 400)
                .environmentObject(chatVM)
                .environmentObject(libraryVM)
                .environmentObject(memoryVM)
        }
        .windowStyle(.automatic)
        .windowToolbarStyle(.unified)
        .defaultSize(width: 1200, height: 800)
        .commands {
            // File
            CommandGroup(after: .newItem) {
                Button("New Chat") {
                    chatVM.newConversation()
                    selectedTab = .chat
                }
                .keyboardShortcut("n", modifiers: .command)
            }

            // View — tab switching
            CommandMenu("View") {
                Button("Chat") { selectedTab = .chat }
                    .keyboardShortcut("1", modifiers: .command)
                Button("Library") { selectedTab = .library }
                    .keyboardShortcut("2", modifiers: .command)
                Button("Memory") { selectedTab = .memory }
                    .keyboardShortcut("3", modifiers: .command)
            }

            // Help
            CommandGroup(replacing: .help) {
                Link("Kindle Brain Documentation",
                     destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
            }
        }

        Settings {
            settingsView
        }
    }

    private var settingsView: some View {
        Form {
            Section("Gemini API") {
                SecureField("API Key", text: Binding(
                    get: { UserDefaults.standard.string(forKey: "geminiAPIKey") ?? "" },
                    set: { UserDefaults.standard.set($0, forKey: "geminiAPIKey") }
                ))
                Text("Get a free key at aistudio.google.com")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section("Data") {
                let dataDir = DataService.shared
                LabeledContent("Data Directory") {
                    Text("~/.kindle-brain/")
                        .textSelection(.enabled)
                }
                Text("Run `kindle-brain setup` to configure your data")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Section("About") {
                LabeledContent("Version", value: "0.1.0")
                Link("Documentation", destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
            }
        }
        .formStyle(.grouped)
        .frame(width: 450, height: 300)
    }
}
