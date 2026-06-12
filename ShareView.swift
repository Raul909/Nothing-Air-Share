import SwiftUI

struct ShareView: View {
    let fileURL: URL?
    var onComplete: () -> Void
    
    @StateObject private var discoveryManager = DiscoveryManager()
    @StateObject private var transferManager = TransferManager()
    
    var body: some View {
        ZStack {
            NothingTheme.black.edgesIgnoringSafeArea(.all)
            
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("SHARE TO NOTHING")
                        .font(NothingTheme.Typography.dotMatrix(size: 20))
                    Spacer()
                    Button {
                        onComplete()
                    } label: {
                        Image(systemName: "xmark")
                            .foregroundColor(NothingTheme.white)
                    }
                }
                .padding(.bottom, 10)
                
                if let url = fileURL {
                    Text("FILE: \(url.lastPathComponent.uppercased())")
                        .font(NothingTheme.Typography.dotMatrix(size: 12))
                        .opacity(0.6)
                }
                
                Text("NEARBY")
                    .font(NothingTheme.Typography.dotMatrix(size: 14))
                    .foregroundColor(NothingTheme.lightGray)
                
                if discoveryManager.discoveredDevices.isEmpty {
                    VStack {
                        Spacer()
                        HStack {
                            Spacer()
                            Text("SEARCHING...")
                                .font(NothingTheme.Typography.dotMatrix(size: 12))
                                .opacity(0.4)
                            Spacer()
                        }
                        Spacer()
                    }
                } else {
                    ScrollView {
                        ForEach(discoveryManager.discoveredDevices) { device in
                            Button {
                                if let url = fileURL {
                                    transferManager.sendFile(url: url, to: device)
                                }
                            } label: {
                                DeviceCard(device: device)
                            }
                            .buttonStyle(PlainButtonStyle())
                        }
                    }
                }
            }
            .padding()
            
            // Progress Overlay
            if case .sending(let progress) = transferManager.state {
                transferOverlay(progress: progress, label: "SENDING...")
            } else if case .completed = transferManager.state {
                transferOverlay(progress: 1.0, label: "SENT")
                    .onAppear {
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                            onComplete()
                        }
                    }
            }
        }
        .preferredColorScheme(.dark)
    }
    
    private func transferOverlay(progress: Double, label: String) -> some View {
        ZStack {
            Color.black.opacity(0.95).edgesIgnoringSafeArea(.all)
            VStack(spacing: 20) {
                Text(label)
                    .font(NothingTheme.Typography.dotMatrix(size: 18))
                Rectangle()
                    .fill(NothingTheme.white)
                    .frame(height: 2)
                    .scaleEffect(x: CGFloat(progress), y: 1, anchor: .leading)
                    .padding(.horizontal, 40)
            }
        }
    }
}
