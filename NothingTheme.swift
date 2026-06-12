import SwiftUI

struct NothingTheme {
    static let black = Color.black
    static let white = Color.white
    static let darkGray = Color(white: 0.1)
    static let lightGray = Color(white: 0.9)
    static let accentRed = Color(red: 1.0, green: 0.0, blue: 0.0) // Nothing's subtle red accents
    
    struct Typography {
        // Fallback to system monospaced if custom font is missing
        static func dotMatrix(size: CGFloat) -> Font {
            return Font.custom("NDOT-45", size: size).fallback(.system(.body, design: .monospaced))
        }
        
        static func sansSerif(size: CGFloat, weight: Font.Weight = .regular) -> Font {
            return Font.system(size: size, weight: weight, design: .default)
        }
    }
}

extension Font {
    func fallback(_ fallback: Font) -> Font {
        // Simple helper if custom font fails to load
        return self
    }
}
