import SwiftUI

@main
struct KindleBrainApp: App {
    @StateObject private var chatVM = ChatViewModel()
    @StateObject private var libraryVM = LibraryViewModel()
    @StateObject private var memoryVM = MemoryViewModel()
    @StateObject private var serverManager = ServerManager.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(chatVM)
                .environmentObject(libraryVM)
                .environmentObject(memoryVM)
                .environmentObject(serverManager)
                .onAppear {
                    serverManager.start()
                }
        }
        .windowStyle(.automatic)
        .defaultSize(width: 1200, height: 800)
        .commands {
            CommandGroup(replacing: .help) {
                Button("Kindle Brain Help") {}
            }
        }
    }
}
