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
    @StateObject private var serverManager = ServerManager.shared

    @FocusedBinding(\.selectedTab) private var selectedTab

    var body: some Scene {
        WindowGroup {
            ContentView()
                .frame(minWidth: 600, minHeight: 400)
                .environmentObject(chatVM)
                .environmentObject(libraryVM)
                .environmentObject(memoryVM)
                .environmentObject(serverManager)
                .onAppear {
                    serverManager.start()
                }
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
            Section("API Server") {
                TextField("Server URL", text: .constant("http://127.0.0.1:8765"))
                    .textFieldStyle(.roundedBorder)
            }
            Section("About") {
                LabeledContent("Version", value: "0.1.0")
                Link("Documentation", destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
            }
        }
        .formStyle(.grouped)
        .frame(width: 450, height: 200)
    }
}
