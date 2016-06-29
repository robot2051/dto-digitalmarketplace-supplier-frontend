from flask.ext.wtf import Form
from wtforms import BooleanField
from wtforms.validators import DataRequired, Length
from dmutils.forms import StripWhitespaceStringField


class SignerDetailsForm(Form):
    full_name = StripWhitespaceStringField('Full name', validators=[
        DataRequired(message="You must provide the full name of the person signing on behalf of the company."),
        Length(max=255, message="You must provide a name under 256 characters.")
    ])
    role = StripWhitespaceStringField(
        'Role at the company',
        validators=[
            DataRequired(message="You must provide the role of the person signing on behalf of the company."),
            Length(max=255, message="You must provide a role under 256 characters.")
        ],
        description='The person signing must have the authority to agree to the framework terms, '
                    'eg director or company secretary.'
    )


class ContractReviewForm(Form):

    def __init__(self, supplier_name, **kwargs):
        super(Form, self).__init__(**kwargs)
        self.supplier_name = supplier_name

    authority = BooleanField(
        'Authorisation',
        validators=[DataRequired(message="You must agree to provide authorisation, please k thanks.")],
        description="I have the authority to return this agreement on behalf of {}".format(self.supplier_name)
    )
