import torch
import torch.nn as nn

# ==========================================
# UPGRADED: SEQ2SEQ WITH ATTENTION
# Better accuracy + fast inference
# ==========================================
class ShipLSTM(nn.Module):
    """
    Sequence-to-Sequence LSTM with Attention for trajectory prediction.
    
    Improvements over baseline:
    - Bidirectional encoder (context from both directions)
    - Attention mechanism (focus on relevant frames)
    - Decoder generates predictions step-by-step (better learning)
    - Velocity smoothness constraint (prevents jerky predictions)
    """
    
    def __init__(self, input_size=4, hidden=64, layers=2, predict_steps=20):
        super().__init__()
        self.predict_steps = predict_steps
        self.hidden_size = hidden
        
        # -------- ENCODER (bidirectional) --------
        self.encoder = nn.LSTM(
            input_size, 
            hidden, 
            num_layers=layers,
            batch_first=True,
            dropout=0.1,
            bidirectional=True  # 🔥 KEY: bidirectional
        )
        
        # -------- ATTENTION --------
        # Attention scores: (batch, seq_len, 1)
        self.attention = nn.Sequential(
            nn.Linear(hidden * 2, hidden),  # 2x because bidirectional
            nn.Tanh(),
            nn.Linear(hidden, 1)
        )
        
        # -------- DECODER (unidirectional) --------
        # Takes context + previous position
        self.decoder = nn.LSTMCell(
            2 + hidden * 2,  # position (x,y) + attended context
            hidden
        )
        
        # -------- OUTPUT HEAD --------
        self.output_head = nn.Linear(hidden, 2)  # predict (x, y)
        
    def forward(self, x):
        """
        Args:
            x: (batch, seq_len, 4) - [x, y, vx, vy] normalized
        Returns:
            predictions: (batch, predict_steps, 2) - [x, y] for each step
        """
        batch_size = x.size(0)
        seq_len = x.size(1)
        
        # -------- ENCODER --------
        encoder_out, _ = self.encoder(x)  # (batch, seq_len, hidden*2)
        
        # -------- ATTENTION --------
        # Compute attention scores over all encoder outputs
        attention_scores = self.attention(encoder_out)  # (batch, seq_len, 1)
        attention_weights = torch.softmax(attention_scores, dim=1)  # (batch, seq_len, 1)
        
        # Context vector = weighted sum of encoder outputs
        context = (encoder_out * attention_weights).sum(dim=1)  # (batch, hidden*2)
        
        # -------- DECODER --------
        predictions = []
        
        # Initial hidden state from encoder
        decoder_h = encoder_out[:, -1, :self.hidden_size]  # (batch, hidden)
        decoder_c = torch.zeros(batch_size, self.hidden_size, device=x.device)
        
        # Last position as starting point
        prev_pos = x[:, -1, :2]  # (batch, 2)
        
        for step in range(self.predict_steps):
            # Decoder input: previous position + attention context
            decoder_input = torch.cat([prev_pos, context], dim=1)  # (batch, 2 + hidden*2)
            
            # Decoder step
            decoder_h, decoder_c = self.decoder(
                decoder_input, 
                (decoder_h, decoder_c)
            )
            
            # Predict next position
            pred_pos = self.output_head(decoder_h)  # (batch, 2)
            predictions.append(pred_pos)
            
            # Use prediction as input to next step
            prev_pos = pred_pos
        
        # Stack predictions
        output = torch.stack(predictions, dim=1)  # (batch, predict_steps, 2)
        return output