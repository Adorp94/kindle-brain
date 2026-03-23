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
    @AppStorage("onboardingComplete") private var onboardingComplete = false

    @FocusedBinding(\.selectedTab) private var selectedTab

    var body: some Scene {
        WindowGroup {
            Group {
                if onboardingComplete {
                    ContentView()
                        .environmentObject(chatVM)
                        .environmentObject(libraryVM)
                } else {
                    OnboardingView()
                }
            }
            .frame(minWidth: 600, minHeight: 400)
            .onChange(of: onboardingComplete) { _, completed in
                if completed {
                    // Reload DataService with the newly configured path
                    DataService.reload()
                    Task { await libraryVM.loadBooks() }
                }
            }
        }
        .windowStyle(.automatic)
        .windowToolbarStyle(.unified)
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(after: .newItem) {
                Button("New Chat") {
                    chatVM.newConversation()
                    selectedTab = .chat
                }
                .keyboardShortcut("n", modifiers: .command)
            }

            CommandMenu("View") {
                Button("Chat") { selectedTab = .chat }
                    .keyboardShortcut("1", modifiers: .command)
                Button("Library") { selectedTab = .library }
                    .keyboardShortcut("2", modifiers: .command)
            }

            CommandGroup(replacing: .help) {
                Link("Kindle Brain Documentation",
                     destination: URL(string: "https://github.com/Adorp94/kindle-brain")!)
            }
        }

        Settings {
            SettingsView()
        }
    }
}
