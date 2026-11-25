use std::fmt::Write as _;

#[derive(Debug, Clone, PartialEq)]
pub enum JsonVal {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<JsonVal>),
    Obj(Vec<(String, JsonVal)>),
}

impl JsonVal {
    pub fn as_str(&self) -> Option<&str> {
        match self {
            JsonVal::Str(s) => Some(s.as_str()),
            _ => None,
        }
    }

    pub fn as_f64(&self) -> Option<f64> {
        match self {
            JsonVal::Num(n) if n.is_finite() => Some(*n),
            _ => None,
        }
    }

    pub fn as_i64(&self) -> Option<i64> {
        match self {
            JsonVal::Num(n) if n.is_finite() && (n.fract().abs() < 1e-9) => Some(n.round() as i64),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            JsonVal::Bool(b) => Some(*b),
            _ => None,
        }
    }

    pub fn as_arr(&self) -> Option<&Vec<JsonVal>> {
        match self {
            JsonVal::Arr(a) => Some(a),
            _ => None,
        }
    }

    pub fn as_obj(&self) -> Option<&Vec<(String, JsonVal)>> {
        match self {
            JsonVal::Obj(o) => Some(o),
            _ => None,
        }
    }

    pub fn get(&self, key: &str) -> Option<&JsonVal> {
        match self {
            JsonVal::Obj(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    #[allow(dead_code)]
    pub fn set(&mut self, key: &str, val: JsonVal) {
        if let JsonVal::Obj(entries) = self {
            if let Some(existing) = entries.iter_mut().find(|(k, _)| k == key) {
                existing.1 = val;
            } else {
                entries.push((key.to_string(), val));
            }
        }
    }

    pub fn to_compact_string(&self) -> String {
        let mut out = String::new();
        self.write_fmt(&mut out, None, 0);
        out
    }

    pub fn to_pretty_string(&self) -> String {
        let mut out = String::new();
        self.write_fmt(&mut out, Some(2), 0);
        out
    }

    fn write_fmt(&self, out: &mut String, indent: Option<usize>, depth: usize) {
        match self {
            JsonVal::Null => out.push_str("null"),
            JsonVal::Bool(b) => out.push_str(if *b { "true" } else { "false" }),
            JsonVal::Num(n) => {
                if !n.is_finite() {
                    out.push_str("null");
                } else if n.fract().abs() < 1e-9 && n.abs() < 9e15 {
                    let _ = write!(out, "{}", n.round() as i64);
                } else {
                    let _ = write!(out, "{}", n);
                }
            }
            JsonVal::Str(s) => write_escaped_str(out, s),
            JsonVal::Arr(arr) => {
                if arr.is_empty() {
                    out.push_str("[]");
                    return;
                }
                out.push('[');
                for (i, item) in arr.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    if let Some(sp) = indent {
                        out.push('\n');
                        for _ in 0..((depth + 1) * sp) {
                            out.push(' ');
                        }
                    }
                    item.write_fmt(out, indent, depth + 1);
                }
                if let Some(sp) = indent {
                    out.push('\n');
                    for _ in 0..(depth * sp) {
                        out.push(' ');
                    }
                }
                out.push(']');
            }
            JsonVal::Obj(entries) => {
                if entries.is_empty() {
                    out.push_str("{}");
                    return;
                }
                out.push('{');
                for (i, (k, v)) in entries.iter().enumerate() {
                    if i > 0 {
                        out.push(',');
                    }
                    if let Some(sp) = indent {
                        out.push('\n');
                        for _ in 0..((depth + 1) * sp) {
                            out.push(' ');
                        }
                    }
                    write_escaped_str(out, k);
                    out.push(':');
                    if indent.is_some() {
                        out.push(' ');
                    }
                    v.write_fmt(out, indent, depth + 1);
                }
                if let Some(sp) = indent {
                    out.push('\n');
                    for _ in 0..(depth * sp) {
                        out.push(' ');
                    }
                }
                out.push('}');
            }
        }
    }
}

pub fn write_escaped_str(out: &mut String, s: &str) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                let _ = write!(out, "\\u{:04x}", c as u32);
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

struct Parser<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Parser<'a> {
    fn skip_ws(&mut self) {
        while self.pos < self.bytes.len() {
            match self.bytes[self.pos] {
                b' ' | b'\t' | b'\r' | b'\n' => self.pos += 1,
                _ => break,
            }
        }
    }

    fn peek(&mut self) -> Option<u8> {
        self.skip_ws();
        self.bytes.get(self.pos).copied()
    }

    fn parse_val(&mut self) -> Result<JsonVal, String> {
        let Some(ch) = self.peek() else {
            return Err("Unexpected end of JSON".to_string());
        };
        match ch {
            b'n' => {
                if self.bytes[self.pos..].starts_with(b"null") {
                    self.pos += 4;
                    Ok(JsonVal::Null)
                } else {
                    Err("Invalid token expecting null".to_string())
                }
            }
            b't' => {
                if self.bytes[self.pos..].starts_with(b"true") {
                    self.pos += 4;
                    Ok(JsonVal::Bool(true))
                } else {
                    Err("Invalid token expecting true".to_string())
                }
            }
            b'f' => {
                if self.bytes[self.pos..].starts_with(b"false") {
                    self.pos += 5;
                    Ok(JsonVal::Bool(false))
                } else {
                    Err("Invalid token expecting false".to_string())
                }
            }
            b'"' => self.parse_str().map(JsonVal::Str),
            b'[' => self.parse_arr(),
            b'{' => self.parse_obj(),
            b'-' | b'0'..=b'9' => self.parse_num(),
            _ => Err(format!("Unexpected character '{}' at {}", ch as char, self.pos)),
        }
    }

    fn parse_hex4(&mut self) -> Result<u16, String> {
        if self.pos + 4 > self.bytes.len() {
            return Err("Truncated \\u escape".to_string());
        }
        let hex_str = std::str::from_utf8(&self.bytes[self.pos..self.pos + 4])
            .map_err(|_| "Invalid UTF-8 in \\u escape".to_string())?;
        let val = u16::from_str_radix(hex_str, 16)
            .map_err(|_| "Invalid hex digits in \\u escape".to_string())?;
        self.pos += 4;
        Ok(val)
    }

    fn parse_str(&mut self) -> Result<String, String> {
        if self.bytes.get(self.pos) != Some(&b'"') {
            return Err("Expected '\"'".to_string());
        }
        self.pos += 1;
        let mut out = String::new();
        while self.pos < self.bytes.len() {
            let b = self.bytes[self.pos];
            if b == b'"' {
                self.pos += 1;
                return Ok(out);
            }
            if b == b'\\' {
                self.pos += 1;
                let esc = *self.bytes.get(self.pos).ok_or("Unterminated escape")?;
                self.pos += 1;
                match esc {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\x08'),
                    b'f' => out.push('\x0c'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let code = self.parse_hex4()?;
                        if (0xD800..=0xDBFF).contains(&code)
                            && self.bytes.get(self.pos..self.pos + 2) == Some(b"\\u")
                        {
                            self.pos += 2;
                            let low = self.parse_hex4()?;
                            let cp = 0x10000 + (((code as u32 - 0xD800) << 10) | (low as u32 - 0xDC00));
                            if let Some(c) = char::from_u32(cp) {
                                out.push(c);
                            }
                        } else if let Some(c) = char::from_u32(code as u32) {
                            out.push(c);
                        }
                    }
                    _ => return Err(format!("Unsupported escape '\\{}'", esc as char)),
                }
            } else if b < 0x80 {
                out.push(b as char);
                self.pos += 1;
            } else {
                let rest = std::str::from_utf8(&self.bytes[self.pos..])
                    .map_err(|_| "Invalid UTF-8 in string".to_string())?;
                let ch = rest.chars().next().ok_or("Unexpected EOF in string")?;
                out.push(ch);
                self.pos += ch.len_utf8();
            }
        }
        Err("Unterminated JSON string".to_string())
    }

    fn parse_num(&mut self) -> Result<JsonVal, String> {
        let start = self.pos;
        if self.bytes.get(self.pos) == Some(&b'-') {
            self.pos += 1;
        }
        let mut has_digits = false;
        while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
            self.pos += 1;
            has_digits = true;
        }
        if !has_digits {
            return Err("Invalid JSON number".to_string());
        }
        if self.bytes.get(self.pos) == Some(&b'.') {
            self.pos += 1;
            let mut frac_digits = false;
            while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                self.pos += 1;
                frac_digits = true;
            }
            if !frac_digits {
                return Err("Invalid fractional number".to_string());
            }
        }
        if matches!(self.bytes.get(self.pos), Some(b'e' | b'E')) {
            self.pos += 1;
            if matches!(self.bytes.get(self.pos), Some(b'+' | b'-')) {
                self.pos += 1;
            }
            let mut exp_digits = false;
            while matches!(self.bytes.get(self.pos), Some(b'0'..=b'9')) {
                self.pos += 1;
                exp_digits = true;
            }
            if !exp_digits {
                return Err("Invalid exponent in number".to_string());
            }
        }
        let s = std::str::from_utf8(&self.bytes[start..self.pos])
            .map_err(|_| "Invalid UTF-8 number".to_string())?;
        let val = s.parse::<f64>().map_err(|_| "Failed parsing float".to_string())?;
        Ok(JsonVal::Num(val))
    }

    fn parse_arr(&mut self) -> Result<JsonVal, String> {
        self.pos += 1;
        let mut items = Vec::new();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Ok(JsonVal::Arr(items));
        }
        loop {
            items.push(self.parse_val()?);
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b']') => {
                    self.pos += 1;
                    return Ok(JsonVal::Arr(items));
                }
                _ => return Err("Expected ',' or ']' in array".to_string()),
            }
        }
    }

    fn parse_obj(&mut self) -> Result<JsonVal, String> {
        self.pos += 1;
        let mut entries = Vec::new();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Ok(JsonVal::Obj(entries));
        }
        loop {
            self.skip_ws();
            let k = self.parse_str()?;
            if self.peek() != Some(b':') {
                return Err("Expected ':' after object key".to_string());
            }
            self.pos += 1;
            let v = self.parse_val()?;
            entries.push((k, v));
            match self.peek() {
                Some(b',') => self.pos += 1,
                Some(b'}') => {
                    self.pos += 1;
                    return Ok(JsonVal::Obj(entries));
                }
                _ => return Err("Expected ',' or '}' in object".to_string()),
            }
        }
    }
}

pub fn parse_json(input: &str) -> Result<JsonVal, String> {
    let trimmed = input.trim_start_matches('\u{FEFF}');
    let mut p = Parser {
        bytes: trimmed.as_bytes(),
        pos: 0,
    };
    let val = p.parse_val()?;
    p.skip_ws();
    if p.pos != p.bytes.len() {
        return Err(format!("Trailing data at byte {}", p.pos));
    }
    Ok(val)
}
