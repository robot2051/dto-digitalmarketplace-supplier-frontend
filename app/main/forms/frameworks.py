from flask.ext.wtf import Form
from wtforms.validators import DataRequired, Length
from dmutils.forms import StripWhitespaceStringField


class SignerDetailsForm(Form):
    full_name = StripWhitespaceStringField('Full name', validators=[
        DataRequired(message="You must provide the full name of the person signing on behalf of the company."),
        Length(max=255, message="You must provide a name under 256 characters.")
    ])
    role = StripWhitespaceStringField('Role at the company', validators=[
        DataRequired(message="You must provide the role of the person signing on behalf of the company."),
        Length(max=255, message="You must provide a role under 256 characters.")
    ])
