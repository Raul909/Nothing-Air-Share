import SwiftUI

struct DashboardView: View {
    @StateObject private var discoveryManager = DiscoveryManager()
    @StateObject private var advertisingManager = AdvertisingManager()
    @StateObject private var transferManager = TransferManager()
    
    // Haptics
    private let discoveryHaptic = UIImpactFeedbackGenerator(style: .medium)
    private let successHaptic = UINotificationFeedbackGenerator()
    
    @State private var showingFileImporter = false
    @State private var selectedDevice: DiscoveredDevice?
    
    var body: some View {
        ZStack {
            NothingTheme.black.edgesIgnoringSafeArea(.all)
            
            // Background Dot Pattern
            DotPatternView()
                .opacity(0.1)
            
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    headerSection
                    
                    // Nothing OS Style Widgets
                    HStack(spacing: 15) {
                        WidgetCard(title: "10:30", subtitle: "AM", icon: "clock.fill")
                        WidgetCard(title: "24°", subtitle: "LONDON", icon: "cloud.sun.fill")
                    }
                    
                    advertisingStatus
                    
                    deviceListSection
                    
                    quickActions
                }
                .padding()
            }
            
            if case .sending(let progress) = transferManager.state {
                transferOverlay(progress: progress, label: "SENDING...")
            } else if case .completed = transferManager.state {
                transferOverlay(progress: 1.0, label: "COMPLETED")
                    .onAppear {
                        successHaptic.notificationOccurred(.success)
                        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                            transferManager.state = .idle
                        }
                    }
            }
        }
        .onChange(of: discoveryManager.discoveredDevices) { devices in
            if !devices.isEmpty {
                discoveryHaptic.impactOccurred()
            }
        }
        .fileImporter(
            isPresented: $showingFileImporter,
            allowedContentTypes: [.data],
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                if let url = urls.first, let device = selectedDevice {
                    transferManager.sendFile(url: url, to: device)
                }
            case .failure(let error):
                print("File selection failed: \(error.localizedDescription)")
            }
        }
    }
    
    private var headerSection: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("NOTHING")
                .font(NothingTheme.Typography.dotMatrix(size: 32))
                .foregroundColor(NothingTheme.white)
            Text("AIRSHARE")
                .font(NothingTheme.Typography.dotMatrix(size: 16))
                .foregroundColor(NothingTheme.accentRed)
        }
        .padding(.top, 20)
    }
    
    private var advertisingStatus: some View {
        HStack {
            Circle()
                .fill(advertisingManager.isAdvertising ? NothingTheme.accentRed : Color.gray)
                .frame(width: 8, height: 8)
            Text(advertisingManager.isAdvertising ? "VISIBLE TO OTHERS" : "HIDDEN")
                .font(NothingTheme.Typography.dotMatrix(size: 10))
                .opacity(0.6)
        }
    }
    
    private var deviceListSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("NEARBY")
                .font(NothingTheme.Typography.dotMatrix(size: 14))
                .foregroundColor(NothingTheme.lightGray)
            
            if discoveryManager.discoveredDevices.isEmpty {
                Text("SEARCHING...")
                    .font(NothingTheme.Typography.dotMatrix(size: 12))
                    .opacity(0.4)
                    .padding()
            } else {
                ForEach(discoveryManager.discoveredDevices) { device in
                    Button {
                        selectedDevice = device
                        showingFileImporter = true
                    } label: {
                        DeviceCard(device: device)
                    }
                    .buttonStyle(PlainButtonStyle())
                }
            }
        }
    }
    
    private var quickActions: some View {
        HStack(spacing: 15) {
            ActionCard(icon: "photo", label: "PHOTOS")
            ActionCard(icon: "doc", label: "FILES")
        }
    }
    
    private func transferOverlay(progress: Double, label: String) -> some View {
        ZStack {
            Color.black.opacity(0.9).edgesIgnoringSafeArea(.all)
            
            VStack(spacing: 30) {
                // Glyph-style Pulse
                Circle()
                    .fill(NothingTheme.accentRed)
                    .frame(width: 12, height: 12)
                    .shadow(color: NothingTheme.accentRed, radius: 10)
                    .opacity(progress > 0.9 ? 1.0 : 0.4)
                    .scaleEffect(progress > 0.9 ? 1.2 : 1.0)
                    .animation(Animation.easeInOut(duration: 0.6).repeatForever(autoreverses: true), value: progress)
                
                Text(label)
                    .font(NothingTheme.Typography.dotMatrix(size: 24))
                
                // Dot-matrix progress bar
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Rectangle()
                            .stroke(NothingTheme.white, lineWidth: 1)
                        
                        Rectangle()
                            .fill(NothingTheme.white)
                            .frame(width: geo.size.width * CGFloat(progress))
                    }
                }
                .frame(height: 40)
                .padding(.horizontal, 40)
                
                Text("\(Int(progress * 100))%")
                    .font(NothingTheme.Typography.dotMatrix(size: 18))
            }
        }
    }
}

struct DeviceCard: View {
    let device: DiscoveredDevice
    
    var body: some View {
        HStack {
            Circle()
                .stroke(NothingTheme.white, lineWidth: 1)
                .frame(width: 40, height: 40)
                .overlay(
                    Text("!") // Placeholder icon
                        .font(NothingTheme.Typography.dotMatrix(size: 20))
                )
            
            VStack(alignment: .leading) {
                Text(device.name.uppercased())
                    .font(NothingTheme.Typography.dotMatrix(size: 16))
                Text("READY TO RECEIVE")
                    .font(NothingTheme.Typography.sansSerif(size: 12))
                    .opacity(0.6)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.caption)
        }
        .padding()
        .background(NothingTheme.darkGray)
        .cornerRadius(12)
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(NothingTheme.lightGray.opacity(0.2), lineWidth: 1)
        )
    }
}

struct WidgetCard: View {
    let title: String
    let subtitle: String
    let icon: String
    
    var body: some View {
        VStack(alignment: .leading) {
            HStack {
                Image(systemName: icon)
                    .font(.system(size: 14))
                Spacer()
            }
            Spacer()
            Text(title)
                .font(NothingTheme.Typography.dotMatrix(size: 24))
            Text(subtitle)
                .font(NothingTheme.Typography.dotMatrix(size: 10))
                .opacity(0.6)
        }
        .padding()
        .frame(maxWidth: .infinity)
        .frame(height: 120)
        .background(NothingTheme.darkGray)
        .cornerRadius(24)
        .overlay(
            RoundedRectangle(cornerRadius: 24)
                .stroke(NothingTheme.lightGray.opacity(0.1), lineWidth: 1)
        )
    }
}

struct ActionCard: View {
    let icon: String
    let label: String
    
    var body: some View {
        VStack {
            Image(systemName: icon)
                .font(.title2)
            Spacer()
            Text(label)
                .font(NothingTheme.Typography.dotMatrix(size: 12))
        }
        .padding()
        .frame(maxWidth: .infinity)
        .frame(height: 100)
        .background(NothingTheme.darkGray)
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(NothingTheme.lightGray.opacity(0.1), lineWidth: 1)
        )
    }
}

struct DotPatternView: View {
    var body: some View {
        GeometryReader { geo in
            Path { path in
                let spacing: CGFloat = 20
                for x in stride(from: 0, through: geo.size.width, by: spacing) {
                    for y in stride(from: 0, through: geo.size.height, by: spacing) {
                        path.addEllipse(in: CGRect(x: x, y: y, width: 2, height: 2))
                    }
                }
            }
            .fill(NothingTheme.white)
        }
    }
}

#Preview {
    DashboardView()
}
